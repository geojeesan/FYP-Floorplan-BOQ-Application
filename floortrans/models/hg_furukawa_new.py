import torch
import torch.nn as nn
import torch.nn.functional as F

class AsymmetricConv2d(nn.Module):
    def __init__(self, in_channels, out_channels, kernel_size=3, stride=1, padding=1):
        super(AsymmetricConv2d, self).__init__()
        # Standard 3x3
        self.conv3x3 = nn.Conv2d(in_channels, out_channels, kernel_size=kernel_size, stride=stride, padding=padding, bias=False)
        # Horizontal 1x3
        self.conv1x3 = nn.Conv2d(in_channels, out_channels, kernel_size=(1, 3), stride=stride, padding=(0, 1), bias=False)
        # Vertical 3x1
        self.conv3x1 = nn.Conv2d(in_channels, out_channels, kernel_size=(3, 1), stride=stride, padding=(1, 0), bias=False)
        
        # Group Normalization + ReLU as per the paper's AC block
        self.gn = nn.GroupNorm(num_groups=min(32, out_channels), num_channels=out_channels)
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x):
        out = self.conv3x3(x) + self.conv1x3(x) + self.conv3x1(x)
        return self.relu(self.gn(out))

class CAM(nn.Module):
    """Channel Attention Module"""
    def __init__(self, in_channels, reduction=16):
        super(CAM, self).__init__()
        self.compress = nn.Conv2d(in_channels, in_channels // 2, kernel_size=1)
        self.avg_pool = nn.AdaptiveAvgPool2d(1)
        self.max_pool = nn.AdaptiveMaxPool2d(1)
        
        mid_channels = max(1, (in_channels // 2) // reduction)
        self.mlp = nn.Sequential(
            nn.Conv2d(in_channels // 2, mid_channels, 1, bias=False),
            nn.ReLU(inplace=True),
            nn.Conv2d(mid_channels, in_channels // 2, 1, bias=False)
        )
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        fc = self.compress(x)
        avg_out = self.mlp(self.avg_pool(fc))
        max_out = self.mlp(self.max_pool(fc))
        mc = self.sigmoid(avg_out + max_out)
        return fc * mc

class SAM(nn.Module):
    """Spatial Attention Module"""
    def __init__(self, in_channels):
        super(SAM, self).__init__()
        self.compress = nn.Conv2d(in_channels, in_channels // 2, kernel_size=1)
        
        # Dilation rates 1, 2, 3 as defined in the paper
        self.conv1x1 = nn.Conv2d(2, 1, kernel_size=1, bias=False)
        self.conv3x3_d1 = nn.Conv2d(2, 1, kernel_size=3, padding=1, dilation=1, bias=False)
        self.conv3x3_d2 = nn.Conv2d(2, 1, kernel_size=3, padding=2, dilation=2, bias=False)
        self.conv3x3_d3 = nn.Conv2d(2, 1, kernel_size=3, padding=3, dilation=3, bias=False)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        fs = self.compress(x)
        avg_out = torch.mean(fs, dim=1, keepdim=True)
        max_out, _ = torch.max(fs, dim=1, keepdim=True)
        pool_out = torch.cat([avg_out, max_out], dim=1)
        
        ms = self.conv1x1(pool_out) + \
             self.conv3x3_d1(pool_out) + \
             self.conv3x3_d2(pool_out) + \
             self.conv3x3_d3(pool_out)
        ms = self.sigmoid(ms)
        return fs * ms

class AttentionModule(nn.Module):
    """Combined Attention Mechanism AM(F)"""
    def __init__(self, in_channels):
        super(AttentionModule, self).__init__()
        self.cam = CAM(in_channels)
        self.sam = SAM(in_channels)
        self.ac = AsymmetricConv2d(in_channels, in_channels, kernel_size=3, stride=1, padding=1)

    def forward(self, x):
        cam_out = self.cam(x)
        sam_out = self.sam(x)
        concat_out = torch.cat([cam_out, sam_out], dim=1)
        return self.ac(concat_out)

class Residual(nn.Module):
    def __init__(self, numIn, numOut):
        super(Residual, self).__init__()
        self.numIn = numIn
        self.numOut = numOut
        self.bn = nn.BatchNorm2d(self.numIn)
        self.relu = nn.ReLU(inplace=True)
        self.conv1 = nn.Conv2d(self.numIn, int(self.numOut / 2), bias=True, kernel_size=1)
        self.bn1 = nn.BatchNorm2d(int(self.numOut / 2))

        # Asymmetric Convolutions
        self.conv2 = AsymmetricConv2d(int(self.numOut / 2), int(self.numOut / 2), stride=1, padding=1)

        self.bn2 = nn.BatchNorm2d(int(self.numOut / 2))
        self.conv3 = nn.Conv2d(int(self.numOut / 2), self.numOut, bias=True, kernel_size=1)

        if self.numIn != self.numOut:
            self.conv4 = nn.Conv2d(self.numIn, self.numOut, bias=True, kernel_size=1)

    def forward(self, x):
        residual = x
        out = self.bn(x)
        out = self.relu(out)
        out = self.conv1(out)
        out = self.bn1(out)
        out = self.relu(out)
        out = self.conv2(out)
        out = self.bn2(out)
        out = self.relu(out)
        out = self.conv3(out)

        if self.numIn != self.numOut:
            residual = self.conv4(x)

        return out + residual

class hg_furukawa_new(nn.Module):
    def __init__(self, n_classes):
        super(hg_furukawa_new, self).__init__()
        self.conv1_ = nn.Conv2d(3, 64, bias=True, kernel_size=7, stride=2, padding=3)
        self.bn1 = nn.BatchNorm2d(64)
        self.relu1 = nn.ReLU(inplace=True)
        self.r01 = Residual(64, 128)
        self.maxpool = nn.MaxPool2d(kernel_size=2, stride=2)
        self.r02 = Residual(128, 128)
        self.r03 = Residual(128, 128)
        self.r04 = Residual(128, 256)

        self.maxpool1 = nn.MaxPool2d(kernel_size=2, stride=2)
        self.r11_a = Residual(256, 256)
        self.r12_a = Residual(256, 256)
        self.r13_a = Residual(256, 256)

        self.maxpool2 = nn.MaxPool2d(kernel_size=2, stride=2)
        self.r21_a = Residual(256, 256)
        self.r22_a = Residual(256, 256)
        self.r23_a = Residual(256, 256)

        self.maxpool3 = nn.MaxPool2d(kernel_size=2, stride=2)
        self.r31_a = Residual(256, 256)
        self.r32_a = Residual(256, 256)
        self.r33_a = Residual(256, 256)

        self.maxpool4 = nn.MaxPool2d(kernel_size=2, stride=2)
        self.r41_a = Residual(256, 256)
        self.r42_a = Residual(256, 256)
        self.r43_a = Residual(256, 256)
        self.r44_a = Residual(256, 512)
        self.r45_a = Residual(512, 512)
        self.upsample4 = nn.ConvTranspose2d(512, 512, kernel_size=2, stride=2)

        self.r41_b = Residual(256, 256)
        self.r42_b = Residual(256, 256)
        self.r43_b = Residual(256, 512)

        self.r4_ = Residual(512, 512)
        self.upsample3 = nn.ConvTranspose2d(512, 512, kernel_size=2, stride=2)

        self.r31_b = Residual(256, 256)
        self.r32_b = Residual(256, 256)
        self.r33_b = Residual(256, 512)

        self.r3_ = Residual(512, 512)
        self.upsample2 = nn.ConvTranspose2d(512, 512, kernel_size=2, stride=2)

        self.r21_b = Residual(256, 256)
        self.r22_b = Residual(256, 256)
        self.r23_b = Residual(256, 512)

        self.r2_ = Residual(512, 512)
        self.upsample1 = nn.ConvTranspose2d(512, 512, kernel_size=2, stride=2)

        self.r11_b = Residual(256, 256)
        self.r12_b = Residual(256, 256)
        self.r13_b = Residual(256, 512)

        # 2. RELOCATED: Attention Mechanism now sits at the bottleneck
        self.attention_module = AttentionModule(512)

        self.conv2_ = nn.Conv2d(512, 512, bias=True, kernel_size=1) 
        self.bn2 = nn.BatchNorm2d(512)
        self.relu2 = nn.ReLU(inplace=True)
        self.conv3_ = nn.Conv2d(512, 256, bias=True, kernel_size=1)
        self.bn3 = nn.BatchNorm2d(256)
        self.relu3 = nn.ReLU(inplace=True)
        self.conv4_ = nn.Conv2d(256, n_classes, bias=True, kernel_size=1)
        self.upsample = nn.ConvTranspose2d(n_classes, n_classes, kernel_size=4, stride=4)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        out = self.conv1_(x)
        out = self.bn1(out)
        out = self.relu1(out)
        out = self.maxpool(out)

        out = self.r01(out)
        out = self.r02(out)
        out = self.r03(out)
        out = self.r04(out)

        out1a = self.maxpool1(out)
        out1a = self.r11_a(out1a)
        out1a = self.r12_a(out1a)
        out1a = self.r13_a(out1a)

        out1b = self.r11_b(out)
        out1b = self.r12_b(out1b)
        out1b = self.r13_b(out1b)

        out2a = self.maxpool2(out1a)
        out2a = self.r21_a(out2a)
        out2a = self.r22_a(out2a)
        out2a = self.r23_a(out2a)

        out2b = self.r21_b(out1a)
        out2b = self.r22_b(out2b)
        out2b = self.r23_b(out2b)

        out3a = self.maxpool3(out2a)
        out3a = self.r31_a(out3a)
        out3a = self.r32_a(out3a)
        out3a = self.r33_a(out3a)

        out3b = self.r31_b(out2a)
        out3b = self.r32_b(out3b)
        out3b = self.r33_b(out3b)

        out4a = self.maxpool4(out3a)
        out4a = self.r41_a(out4a)
        out4a = self.r42_a(out4a)
        out4a = self.r43_a(out4a)
        out4a = self.r44_a(out4a)
        out4a = self.r45_a(out4a)

        out4b = self.r41_b(out3a)
        out4b = self.r42_b(out4b)
        out4b = self.r43_b(out4b)
        
        # 1. THE RESIDUAL ATTENTION FIX
        # The pre-trained features pass through cleanly, while attention adds context safely
        attention_context = self.attention_module(out4a)
        out4a = out4a + attention_context

        # 2. RESTORE THE PRE-TRAINED DECODER (Addition)
        out4_ = self.upsample4(out4a)
        out4 = self._upsample_add(out4_, out4b)
        out4 = self.r4_(out4)

        out3_ = self.upsample3(out4)
        out3 = self._upsample_add(out3_, out3b)
        out3 = self.r3_(out3)

        out2_ = self.upsample2(out3)
        out2 = self._upsample_add(out2_, out2b)
        out2 = self.r2_(out2)

        out1_ = self.upsample1(out2)
        out = self._upsample_add(out1_, out1b)

        # Final classification layers
        out = self.conv2_(out)
        out = self.bn2(out)
        out = self.relu2(out)
        out = self.conv3_(out)
        out = self.bn3(out)
        out = self.relu3(out)
        out = self.conv4_(out)
        out = self.upsample(out)

        out[:, :21] = self.sigmoid(out[:, :21])
        return out

    def _upsample_concat(self, x, y, fuse_block):
        # Literature implementation: Concatenate instead of add to preserve edge details
        _, _, H, W = y.size()
        if y.shape[2:] != x.shape[2:]:
            x = F.interpolate(x, size=(H, W), mode='bilinear', align_corners=False)
        
        # Concatenate along channel dimension
        cat_out = torch.cat([x, y], dim=1)
        return fuse_block(cat_out)

    def _upsample_add(self, x, y):
        _, _, H, W = y.size()
        if y.shape != x.shape:
            return F.interpolate(x, size=(H, W), mode='bilinear', align_corners=False) + y
        else:
            return x + y
            
    def init_weights(self):
        # We bypass this because we are handling the custom AsymmetricConv2d 
        # weight surgery explicitly inside train_newer.py
        pass