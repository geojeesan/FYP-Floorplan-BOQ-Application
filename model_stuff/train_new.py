import matplotlib
matplotlib.use('pdf')
import sys
import os
import logging
import json
import argparse
import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
import pandas as pd
from datetime import datetime
from floortrans.loaders.augmentations import (RandomCropToSizeTorch, ResizePaddedTorch, Compose, DictToTensor, ColorJitterTorch, RandomRotations)
from torchvision.transforms import RandomChoice
from torch.utils import data
from torch.nn.functional import softmax
from tqdm import tqdm
from floortrans.loaders import FloorplanSVG
from floortrans.models import get_model
from floortrans.losses import UncertaintyLoss
from floortrans.metrics import get_px_acc, runningScore
from tensorboardX import SummaryWriter
from torch.optim.lr_scheduler import ReduceLROnPlateau
import torch.cuda.amp # Mixed Precision

torch.backends.cudnn.benchmark = True

def train(args, log_dir, writer, logger):
    with open(log_dir+'/args.json', 'w') as out:
        json.dump(vars(args), out, indent=4)

    # Augmentation
    aug_list = [RandomCropToSizeTorch(data_format='dict', size=(args.image_size, args.image_size)),
                RandomRotations(format='cubi'), DictToTensor(), ColorJitterTorch()]
    if args.scale:
        aug_list[0] = RandomChoice([RandomCropToSizeTorch(data_format='dict', size=(args.image_size, args.image_size)),
                                     ResizePaddedTorch((0, 0), data_format='dict', size=(args.image_size, args.image_size))])
    aug = Compose(aug_list)

    # Data Loaders
    train_set = FloorplanSVG(args.data_path, 'train.txt', format='lmdb', augmentations=aug)
    val_set = FloorplanSVG(args.data_path, 'val.txt', format='lmdb', augmentations=DictToTensor())
    
    num_workers = 0 if args.debug else 8
    
    trainloader = data.DataLoader(train_set, batch_size=args.batch_size, num_workers=num_workers, shuffle=True, pin_memory=True)
    valloader = data.DataLoader(val_set, batch_size=1, num_workers=num_workers, pin_memory=True)

    # Model Setup
    input_slice = [21, 12, 11]
    if args.arch == 'hg_furukawa_new':
        model = get_model(args.arch, 51)
        criterion = UncertaintyLoss(input_slice=input_slice)
        
        if args.furukawa_weights:
            logger.info(f"Loading furukawa weights: {args.furukawa_weights}")
            checkpoint = torch.load(args.furukawa_weights)
            model.load_state_dict(checkpoint['model_state'])
            criterion.load_state_dict(checkpoint['criterion_state'])
            
        model.conv4_ = torch.nn.Conv2d(256, args.n_classes, bias=True, kernel_size=1)
        model.upsample = torch.nn.ConvTranspose2d(args.n_classes, args.n_classes, kernel_size=4, stride=4)
        for m in [model.conv4_, model.upsample]:
            nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
            nn.init.constant_(m.bias, 0)
    else:
        model = get_model(args.arch, args.n_classes)
        criterion = UncertaintyLoss(input_slice=input_slice)

    model.cuda()
    # scaler = torch.cuda.amp.GradScaler() 
    
    if torch.cuda.device_count() > 1:
        logger.info(f"Let's use {torch.cuda.device_count()} GPUs!")
        model = nn.DataParallel(model)

    # Optimizer
    params = [{'params': model.parameters(), 'lr': args.l_rate}, {'params': criterion.parameters(), 'lr': args.l_rate}]
    
    if args.optimizer == 'adam-patience':
        optimizer = torch.optim.Adam(params, eps=1e-8, betas=(0.9, 0.999))
        scheduler = ReduceLROnPlateau(optimizer, 'min', patience=args.patience, factor=0.5)
    elif args.optimizer == 'sgd':
        optimizer = torch.optim.SGD(params, momentum=0.9, weight_decay=10**-4, nesterov=True)
    else:
        optimizer = torch.optim.Adam(params, eps=1e-8, betas=(0.9, 0.999))

    start_epoch = 0
    best_val_loss = float('inf')

    # Full Checkpoint Loading with Smart Surgery
    if args.weights:
        if os.path.exists(args.weights):
            print(f"Resuming training from: {args.weights}")
            logger.info(f"Loading weights from {args.weights}")
            checkpoint = torch.load(args.weights)
            
            # 1. Check if we are loading Model A or resuming an Asymmetric run
            if any('conv1x3' in k for k in checkpoint['model_state'].keys()):
                # This is an already-upgraded checkpoint. Standard resume.
                print("Detected native asymmetric weights. Resuming directly...")
                model.load_state_dict(checkpoint['model_state'])
                
                # 2. Restore Loss and Optimizer States ONLY if resuming
                if 'criterion_state' in checkpoint:
                    criterion.load_state_dict(checkpoint['criterion_state'])
                if 'optimizer_state' in checkpoint:
                    optimizer.load_state_dict(checkpoint['optimizer_state'])
                if 'epoch' in checkpoint:
                    start_epoch = checkpoint['epoch']
                    print(f"Resuming from epoch {start_epoch}")
                    
            else:
                # This is a Model A checkpoint. Perform surgery.
                print("Detected standard weights. Performing weight surgery...")
                old_state = checkpoint['model_state']
                new_state = model.state_dict()
                
                for key, tensor in old_state.items():
                    if key in new_state and new_state[key].shape == tensor.shape:
                        new_state[key].copy_(tensor)
                    elif "conv2.weight" in key:
                        new_key = key.replace("conv2.weight", "conv2.conv3x3.weight")
                        if new_key in new_state:
                            new_state[new_key].copy_(tensor)
                    elif "conv2.bias" in key:
                        new_key = key.replace("conv2.bias", "conv2.conv3x3.bias")
                        if new_key in new_state:
                            new_state[new_key].copy_(tensor)

                for name, param in model.named_parameters():
                    if 'conv1x3.weight' in name or 'conv3x1.weight' in name:
                        nn.init.constant_(param, 0.0)

                model.load_state_dict(new_state)
                
                # Crucial: We purposefully do NOT load the old optimizer or criterion states here.
                print("Surgery complete. Starting loss and optimizer fresh for the upgraded architecture.")
                start_epoch = 0
                
        else:
            print(f"Warning: Weights file not found at {args.weights}")

    print(f"Starting training... Logs will be saved to {log_dir}")

    # --- RESTORED EPOCH LOOP ---
    for epoch in range(start_epoch, args.n_epoch):
        model.train()
        train_losses = []
        print(f"Epoch [{epoch+1}/{args.n_epoch}]")

        for i, samples in tqdm(enumerate(trainloader), total=len(trainloader), ncols=80, leave=False):
            images = samples['image'].cuda(non_blocking=True)
            labels = samples['label'].cuda(non_blocking=True)

            optimizer.zero_grad()

            outputs = model(images)
            loss = criterion(outputs, labels)

            loss.backward()
            optimizer.step()

            train_losses.append(loss.item())

        avg_train_loss = np.mean(train_losses)
        writer.add_scalar('training/loss', avg_train_loss, global_step=epoch)
        logger.info(f"Epoch [{epoch+1}/{args.n_epoch}] Training Loss: {avg_train_loss:.4f}")

        # --- VALIDATE EVERY EPOCH ---
        # A Plateau Scheduler needs constant updates to work effectively.
        model.eval()
        val_losses = []

        with torch.no_grad():
            for samples_val in tqdm(valloader, total=len(valloader), ncols=80, leave=False, desc="Validating"):
                images_val = samples_val['image'].cuda(non_blocking=True)
                labels_val = samples_val['label'].cuda(non_blocking=True)

                outputs = model(images_val)
                labels_val = F.interpolate(labels_val, size=outputs.shape[2:], mode='bilinear', align_corners=False)
                v_loss = criterion(outputs, labels_val)

                val_losses.append(v_loss.item())

        avg_val_loss = np.mean(val_losses)
        writer.add_scalar('validation/loss', avg_val_loss, global_step=epoch)
        logger.info(f"Epoch [{epoch+1}/{args.n_epoch}] Validation Loss: {avg_val_loss:.4f}")

        # Step the scheduler based on validation loss EVERY epoch
        if args.optimizer == 'adam-patience':
            scheduler.step(avg_val_loss)

        # Save Best Model
        if avg_val_loss < best_val_loss:
            best_val_loss = avg_val_loss
            logger.info("New best validation loss found. Saving model...")
            state = {
                'epoch': epoch + 1,
                'model_state': model.state_dict(),
                'criterion_state': criterion.state_dict(),
                'optimizer_state': optimizer.state_dict(),
                'best_val_loss': best_val_loss
            }
            torch.save(state, f"{log_dir}/model_best_val_loss.pkl")

        # Save latest model at the end of EVERY epoch
        state = {
            'epoch': epoch + 1,
            'model_state': model.state_dict(),
            'criterion_state': criterion.state_dict(),
            'optimizer_state': optimizer.state_dict()
        }
        torch.save(state, f"{log_dir}/model_latest.pkl")

    print("Training finished. Latest and best models saved.")

if __name__ == '__main__':
    time_stamp = datetime.now().strftime("%Y-%m-%d-%H:%M:%S")
    parser = argparse.ArgumentParser()
    
    parser.add_argument('--arch', default='hg_furukawa_new')
    parser.add_argument('--data-path', default='data/cubicasa5k/')
    parser.add_argument('--n-classes', type=int, default=44)
    parser.add_argument('--batch-size', type=int, default=26)
    parser.add_argument('--image-size', type=int, default=256)
    parser.add_argument('--l-rate', type=float, default=1e-3)
    parser.add_argument('--log-path', default='runs_cubi/')
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--scale', action='store_true')
    
    # Restored Arguments
    parser.add_argument('--n-epoch', type=int, default=200, help='Total number of epochs to train')
    parser.add_argument('--weights', default=None, help='Path to .pkl model to resume')
    parser.add_argument('--furukawa-weights', default=None)
    parser.add_argument('--optimizer', default='adam-patience')
    parser.add_argument('--patience', type=int, default=10)

    args = parser.parse_args()

    # Create directory
    log_dir = args.log_path + '/' + time_stamp + '/'
    os.makedirs(log_dir, exist_ok=True)
    
    writer = SummaryWriter(log_dir)
    logger = logging.getLogger('train')
    logger.setLevel(logging.INFO)
    
    train(args, log_dir, writer, logger)
