#!/bin/bash
#SBATCH --job-name=model_evaluation
#SBATCH --ntasks=4
#SBATCH --mem=32G
#SBATCH --time=2:00:00
#SBATCH --qos=bbgpu           # Required for jobs that need a GPU
#SBATCH --gpus=1              # Request 1 GPU
#SBATCH --account=chenhp-boq  # Associates the job with your project code

# Fail on first error (recommended by BlueBEAR)
set -e

# Reset environment and load standard BlueBEAR profile (required)
module purge; module load bluebear

# Note: Slurm automatically runs the script in the directory you submitted it from.
# If you submit this from within your chenhp-boq folder, you don't need to cd.

echo "Starting evaluation job on $(hostname)..."

# Run the python script directly inside the Apptainer container
# We removed the JupyterLab parts because Slurm will run this in the background
apptainer exec --nv cubi.sif python eval.py --weights runs_cubi/2026-03-17-23:24:08/model_best_val_loss.pkl

echo "Evaluation job completed successfully!"
