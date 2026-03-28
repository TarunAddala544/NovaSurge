#!/usr/bin/env python3
"""
NovaSurge - LSTM Autoencoder Trainer
Trains an LSTM autoencoder for sequence-based anomaly detection.
"""

import pandas as pd
import numpy as np
import json
import os
import pickle
from datetime import datetime

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

# Feature columns
FEATURE_COLS = [
    "http_request_rate",
    "error_rate",
    "p99_latency",
    "cpu_usage",
    "memory_usage",
    "active_connections",
]


class LSTMAutoencoder(nn.Module):
    """LSTM Autoencoder for anomaly detection."""

    def __init__(self, input_size=6, hidden_size=64, num_layers=2):
        super(LSTMAutoencoder, self).__init__()
        self.hidden_size = hidden_size
        self.num_layers = num_layers

        # Encoder
        self.encoder = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
        )

        # Decoder
        self.decoder = nn.LSTM(
            input_size=hidden_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
        )

        # Output layer
        self.output_layer = nn.Linear(hidden_size, input_size)

    def forward(self, x):
        # x shape: (batch, seq_len, input_size)
        batch_size = x.size(0)

        # Encode
        _, (hidden, cell) = self.encoder(x)
        # hidden shape: (num_layers, batch, hidden_size)

        # Prepare decoder input - repeat hidden state for each timestep
        decoder_input = hidden[-1].unsqueeze(1).repeat(1, x.size(1), 1)
        # decoder_input shape: (batch, seq_len, hidden_size)

        # Decode
        decoder_output, _ = self.decoder(decoder_input, (hidden, cell))
        # decoder_output shape: (batch, seq_len, hidden_size)

        # Output
        output = self.output_layer(decoder_output)
        # output shape: (batch, seq_len, input_size)

        return output


def create_sequences(data, seq_length=10):
    """Create sequences for LSTM training."""
    sequences = []
    for i in range(len(data) - seq_length + 1):
        seq = data[i : i + seq_length]
        sequences.append(seq)
    return np.array(sequences)


def train_lstm(
    data_path="novasurge/data/synthetic_baseline.csv",
    model_path="novasurge/models/lstm.pt",
    threshold_path="novasurge/models/lstm_threshold.json",
    seq_length=10,
    batch_size=32,
    epochs=50,
    learning_rate=0.001,
):
    """Train LSTM autoencoder on baseline data."""

    print(f"Loading data from {data_path}...")
    df = pd.read_csv(data_path)

    # Load scaler for consistent preprocessing
    scaler_path = model_path.replace("lstm.pt", "scaler.pkl")
    with open(scaler_path, "rb") as f:
        scaler = pickle.load(f)

    print(f"Preparing sequences (length={seq_length})...")

    # Prepare sequences per service
    all_sequences = []
    services = df["service"].unique()

    for service in services:
        service_df = df[df["service"] == service].sort_values("timestamp")
        features = service_df[FEATURE_COLS].values
        features_scaled = scaler.transform(features)

        # Create sequences
        seqs = create_sequences(features_scaled, seq_length)
        all_sequences.extend(seqs)

    all_sequences = np.array(all_sequences)
    print(f"Total sequences: {len(all_sequences)}")

    # Convert to tensors
    X = torch.FloatTensor(all_sequences)
    dataset = TensorDataset(X, X)  # Autoencoder: input = target
    dataloader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

    # Initialize model
    device = torch.device("cpu")  # CPU-only as specified
    model = LSTMAutoencoder(input_size=6, hidden_size=64, num_layers=2).to(device)

    # Loss and optimizer
    criterion = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)

    print(f"\n🚀 Training LSTM Autoencoder...")
    print(f"  Epochs: {epochs}")
    print(f"  Batch size: {batch_size}")
    print(f"  Learning rate: {learning_rate}")
    print(f"  Device: {device}")

    # Training loop
    losses = []
    for epoch in range(epochs):
        epoch_losses = []
        for batch_x, batch_y in dataloader:
            batch_x = batch_x.to(device)
            batch_y = batch_y.to(device)

            # Forward
            output = model(batch_x)
            loss = criterion(output, batch_y)

            # Backward
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            epoch_losses.append(loss.item())

        avg_loss = np.mean(epoch_losses)
        losses.append(avg_loss)

        if (epoch + 1) % 10 == 0 or epoch == 0:
            print(f"  Epoch {epoch + 1}/{epochs}, Loss: {avg_loss:.6f}")

    # Calculate reconstruction errors for threshold
    print("\n📊 Calculating reconstruction errors...")
    model.eval()
    reconstruction_errors = []

    with torch.no_grad():
        for batch_x, batch_y in dataloader:
            batch_x = batch_x.to(device)
            output = model(batch_x)
            error = torch.mean((output - batch_x) ** 2, dim=(1, 2))
            reconstruction_errors.extend(error.cpu().numpy())

    reconstruction_errors = np.array(reconstruction_errors)
    mean_error = float(np.mean(reconstruction_errors))
    std_error = float(np.std(reconstruction_errors))
    threshold = mean_error + 2 * std_error

    print(f"  Mean reconstruction error: {mean_error:.6f}")
    print(f"  Std reconstruction error: {std_error:.6f}")
    print(f"  Threshold (mean + 2*std): {threshold:.6f}")

    # Save model
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    torch.save(
        {
            "model_state_dict": model.state_dict(),
            "config": {
                "input_size": 6,
                "hidden_size": 64,
                "num_layers": 2,
                "seq_length": seq_length,
            },
        },
        model_path,
    )
    print(f"\n✅ Model saved to: {os.path.abspath(model_path)}")

    # Save threshold
    threshold_data = {
        "threshold": threshold,
        "mean_error": mean_error,
        "std_error": std_error,
        "seq_length": seq_length,
    }
    with open(threshold_path, "w") as f:
        json.dump(threshold_data, f, indent=2)
    print(f"✅ Threshold saved to: {os.path.abspath(threshold_path)}")

    print(f"\n🚀 LSTM training complete!")
    print(f"   Final loss: {losses[-1]:.6f}")
    print(f"   Threshold: {threshold:.6f}")

    return model, threshold_data


if __name__ == "__main__":
    model, threshold = train_lstm()
