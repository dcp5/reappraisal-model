# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/Trainers.ipynb (unless otherwise specified).

__all__ = []

# Cell
%load_ext autoreload
#default_exp trainers
#export
import datetime
import logging
import os
import tempfile
from os.path import dirname

import torch
import pandas as pd
import pytorch_lightning as lit
import wandb
from pytorch_lightning.callbacks import EarlyStopping, ModelCheckpoint
from pytorch_lightning.loggers import TensorBoardLogger, CSVLogger, WandbLogger

from .lightningreapp import LightningReapp
from .utils import upload_file

# Internal Cell
default_config = {
    'lr': 1e-3,
    'hidden_layer_size': 50
    }

#export
def kfold_train(k: int, ldhdata, strat, s3_bucket=None, **trainer_kwargs) -> None:
    """Fits a LightningReapp instance with k-fold cross-validation.
    Args:
        k (int):
        ldhdata : See `reappraisalmodel.ldhdata.LDHDataModule`
    """
    all_metrics = []

    max_epochs = trainer_kwargs.pop('max_epochs', 20)
    gpus = trainer_kwargs.pop('gpus', 1 if torch.cuda.is_available() else None)

    today = datetime.datetime.today().strftime('%Y%m%d_%H%M%S')

    #Create temporary data to store checkpoint files.
    with tempfile.TemporaryDirectory() as tempdir:
        print(f'Created temporary directory: {tempdir}')

        for i in range(k):
            # Select the dataloaders for the given split.
            split = i
            train_dl = ldhdata.get_train_dataloader(split)
            val_dl = ldhdata.get_val_dataloader(split)

            save_dir='reapp_logs'
            name=f"{i:02d}foldCV_{strat}_{today}"
            version="split"
            prefix=i

            # Loggers
            logger = TensorBoardLogger(
                save_dir=save_dir,
                name=name,
                version=version,
                prefix=prefix
            )

            csv_logger = CSVLogger(
                save_dir=save_dir,
                name=name,
                version=version,
                prefix=prefix
            )

            #Checkpoints
            early_stop_checkpoint = EarlyStopping(
                monitor='val_loss',
                mode='min',
                min_delta=0.001,
                patience=3,
                verbose=False
            )

            callback_checkpoint = ModelCheckpoint(
                monitor='val_loss',
                mode='min',
                dirpath=os.path.join(tempdir, name),
                filename= f'{split}_'+'{epoch:02d}-{val_loss:.02f}',
                verbose=False,
                save_last=False,
                save_top_k=1,
                save_weights_only=False,
            )

            model = LightningReapp(default_config)
            trainer = lit.Trainer(
                benchmark=True,
                logger = [logger, csv_logger],
                gpus = gpus,
                gradient_clip_val=1.0,
                max_epochs=max_epochs,
                terminate_on_nan=True,
                weights_summary=None,
                callbacks=[callback_checkpoint, early_stop_checkpoint],
                **trainer_kwargs)
            print(f"Training on split {i}")
            trainer.fit(model, train_dl, val_dl)
            all_metrics.append({
                'metrics': trainer.logged_metrics,
                'checkpoint': callback_checkpoint.best_model_path,
                'num_epochs': trainer.current_epoch
            })

        outputs = []
        for split in all_metrics:
            val_loss = split['metrics']['val_loss'].item()
            train_loss = split['metrics']['train_loss'].item()
            num_epochs = split['num_epochs']
            r2score = split['metrics']['r2score']
            explained_variance = split['metrics']['explained_var']

            ckpt_path = split['checkpoint']
            filename = os.path.split(ckpt_path)[-1]

            upload_result = upload_file(ckpt_path, 'ldhdata', f'{strat}/{i}-{str(today)}-{filename}')
            print(f"Successful {filename} to s3: {upload_result}")

            row = {
                'val_loss': val_loss,
                'train_loss': train_loss,
                'num_epochs': num_epochs,
                'r2score': r2score,
                'explained_var': explained_variance
            }
            print(row)
            outputs.append(row)
        df = pd.DataFrame(outputs)
        df['r2score'] = df['r2score'].apply(lambda x: x.item())
        df['explained_var'] = df['explained_var'].apply(lambda x: x.item())

        report_name = f'{str(today)}-report.csv'
        report_path = os.path.join(tempdir, f"{strat}-{report_name}" )
        df.to_csv(report_path)
        if s3_bucket is not None:
            upload_report = upload_file(report_path, s3_bucket, f'{strat}/{report_name}')
            print(f"Successful Uploading Report to s3: {upload_report}")
        print(df.describe())
        return df