# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/LightningReapp.ipynb (unless otherwise specified).

__all__ = ['LightningReapp', 'get_avg_masked_encoding', 'default_model_name']

# Cell
import pickle
import path

import pandas as pd
import pytorch_lightning as lit
import torch
from pytorch_lightning.metrics.functional import r2score, explained_variance
from torch import nn, optim
from torch.nn import functional as F
from transformers import AutoModel

default_model_name = "distilbert-base-uncased-finetuned-sst-2-english"


class LightningReapp(lit.LightningModule):
    def __init__(self, config, pretrained_model_name=default_model_name):
        super().__init__()

        self.lr = config["lr"]
        self.hidden_layer_size = config["hidden_layer_size"]
        self.save_hyperparameters()

        # Initialize a pretrained model
        self.bert = AutoModel.from_pretrained(pretrained_model_name)

        # Turn off autograd for bert encoder
        for param in self.bert.parameters():
            param.requires_grad = False

        self.classifier = nn.Sequential(
            nn.Linear(768, self.hidden_layer_size),
            nn.ReLU(),
            nn.Linear(self.hidden_layer_size, 7),
            nn.ReLU(),
        )

        # define metrics
        self.train_loss = lit.metrics.MeanSquaredError()
        self.val_loss = lit.metrics.MeanSquaredError()

    def forward(self, input_ids, attention_mask):
        output = self.bert(input_ids, attention_mask)
        last_hidden_state = output.last_hidden_state
        avg = get_avg_masked_encoding(last_hidden_state, attention_mask)
        out = self.classifier(avg).squeeze()
        return out

    def configure_optimizers(self):
        optimizer = optim.Adam(self.parameters(), lr=self.lr)
        return optimizer

    def training_step(self, batch, batch_idx):
        # destructure batch
        input_ids = batch["input_ids"]
        attention_mask = batch["attention_mask"]
        score = batch["score"]
        # Compute the loss
        output = self(input_ids, attention_mask)
        loss = self.train_loss(output.sum(dim=1), score)
        self.log("train_loss", loss)
        return {"loss": loss}

    def training_epoch_end(self, outputs):
        avg_loss = torch.stack([x["loss"] for x in outputs]).mean()
        self.log("train_loss", avg_loss)

    # VALIDATION LOOP
    def validation_step(self, batch, batch_idx):
        input_ids = batch["input_ids"]
        attention_mask = batch["attention_mask"]
        expected = batch["score"]
        output = self(input_ids, attention_mask)
        observed = output.sum(dim=1)
        loss = self.val_loss(observed, expected)
        return {
            "val_loss": loss,
            'r2score': r2score(observed, expected),
            'explained_var': explained_variance(observed, expected)
        }

    def validation_epoch_end(self, outputs):
<<<<<<< HEAD
        avg_loss = torch.stack([x["loss"] for x in outputs]).mean()
        # observed = torch.stack([x["observed"] for x in outputs])
        # expected = torch.stack([x["expected"] for x in outputs])
=======
        avg_loss = torch.stack([x["val_loss"] for x in outputs]).mean()
        r2score = torch.stack([x["r2score"] for x in outputs]).mean()
        explained_var = torch.stack([x["explained_var"] for x in outputs]).mean()

>>>>>>> add-metrics
        # calculate spearman's r and pearson's r
        self.log("val_loss", avg_loss)
        self.log('r2score', r2score.item())
        self.log('explained_var', explained_var.item())


    # TESTING LOOP
    def test_step(self, batch, batch_idx):
        input_ids = batch["input_ids"]
        attention_mask = batch["attention_mask"]
        output = self(input_ids, attention_mask)
        # Eval step
        return {"predict": (batch_idx, output.sum(dim=1))}

    def test_epoch_end(self, outputs):
        dfs = []
        for output in outputs:
            batch_idx, result = output['predict']
            dfs.append((batch_idx, result.cpu().tolist()))
        with open(f"./output_reapp.pkl", 'wb+') as f:
            pickle.dump(dfs, f)



# export
def get_avg_masked_encoding(state: torch.Tensor, attention_mask: torch.Tensor):
    """[summary]
    For B = batch size, L = encoding length, F = feature vector:
    Args:
        state (torch.Tensor): (B, L, F)
        attention_mask (torch.Tensor): (B, L)
    Returns:
        torch.Tensor: (B, F), where L has been masked by `attention_mask` and then averaged.
            Each vector in the batch represents the average feature vector for the masked_encoding
    """
    encodings = state.unbind(dim=0)  # split the batch up
    new_tensors = []
    # TODO: VECTORIZE
    for i in range(len(encodings)):
        # for each element in the encoding dimension, get the elements that aren't padding using the attention_mask
        encoding_mask = attention_mask[i]
        # Find the indices where attention_mask > 0 (where the actual tokens are without padding)
        indices = encoding_mask.nonzero(as_tuple=True)[0]
        masked_encoding = (
            encodings[i].index_select(0, indices).squeeze()
        )  # torch.Size([len(indices), F])
        avg_feature = torch.mean(masked_encoding, dim=0)
        new_tensors.append(avg_feature)

    return torch.stack(new_tensors)