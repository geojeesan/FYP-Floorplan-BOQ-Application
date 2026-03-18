#!/bin/bash
#SBATCH --job-name=model_training
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=18:00:00       # Adjust this to how long your training usually takes (HH:MM:SS)
#SBATCH --qos=bbgpu           # Required for jobs that need a GPU
#SBATCH --gpus=2              # Request 2 GPU
#SBATCH --account=chenhp-boq  # Associates the job with your project code

# Fail on first error (recommended by BlueBEAR)
set -e

# Reset environment and load standard BlueBEAR profile (required)
module purge; module load bluebear

# Note: Slurm automatically runs the script in the directory you submitted it from.
# If you submit this from within your chenhp-boq folder, you don't need to cd.

echo "Starting training job on $(hostname)..."

# Run the python script directly inside the Apptainer container
# We removed the JupyterLab parts because Slurm will run this in the background
apptainer exec --nv cubi.sif python train_newest.py --weights model_best_val_loss_var.pkl --n-epoch 150 --batch-size 40

echo "Training job completed successfully!"
