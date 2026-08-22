"""Train in Rust, verify with NumPy/Python, and plot with Matplotlib."""

from math import exp
from pathlib import Path
from time import perf_counter

import matplotlib.pyplot as plt
import numpy as np

from crabwalk import rust

libm = rust.crate("libm", version="0.2")


@rust.fn
def train_logistic(
    features: rust.Owned[rust.Vec[rust.f64]],
    labels: rust.Owned[rust.Vec[rust.f64]],
    sample_count: rust.f64,
    epochs: rust.usize,
    learning_rate: rust.f64,
) -> rust.Tuple[rust.f64, rust.f64]:
    # Owned<Vec<f64>> transfers both buffers into native code for this call.
    weight: rust.f64 = 0.0
    bias: rust.f64 = 0.0
    epoch: rust.usize = 0
    while epoch < epochs:
        gradient_weight: rust.f64 = 0.0
        gradient_bias: rust.f64 = 0.0
        index: rust.usize = 0
        while index < features.len():
            score: rust.f64 = weight * features[index] + bias
            negative_score: rust.f64 = -score
            exponential: rust.f64 = libm.exp(negative_score)
            error: rust.f64 = 1.0 / (1.0 + exponential) - labels[index]
            gradient_weight += error * features[index]
            gradient_bias += error
            index += 1
        weight -= learning_rate * gradient_weight / sample_count
        bias -= learning_rate * gradient_bias / sample_count
        epoch += 1
    return weight, bias


def train_python(features, labels, epochs, learning_rate):
    weight = bias = 0.0
    for _ in range(epochs):
        gradient_weight = gradient_bias = 0.0
        for feature, label in zip(features, labels, strict=True):
            error = 1.0 / (1.0 + exp(-(weight * feature + bias))) - label
            gradient_weight += error * feature
            gradient_bias += error
        weight -= learning_rate * gradient_weight / len(features)
        bias -= learning_rate * gradient_bias / len(features)
    return weight, bias


def train_numpy(features, labels, epochs, learning_rate):
    weight = bias = 0.0
    for _ in range(epochs):
        errors = 1.0 / (1.0 + np.exp(-(weight * features + bias))) - labels
        weight -= learning_rate * float(np.mean(errors * features))
        bias -= learning_rate * float(np.mean(errors))
    return weight, bias


if __name__ == "__main__":
    rng = np.random.default_rng(7)
    features = np.linspace(-3.0, 3.0, 400) + rng.normal(0.0, 0.25, 400)
    labels = (features + rng.normal(0.0, 0.8, 400) > 0.0).astype(float)
    epoch_count, learning_rate = 5_000, 0.08
    feature_list, label_list = features.tolist(), labels.tolist()
    rust_features = rust.Vec[rust.f64](feature_list)
    rust_labels = rust.Vec[rust.f64](label_list)

    started = perf_counter()
    weight, bias = train_logistic(
        rust_features,
        rust_labels,
        float(features.size),
        epoch_count,
        learning_rate,
    )
    rust_ms = (perf_counter() - started) * 1_000

    # Owned arguments are observably moved after the native call consumes them.
    assert rust_features.moved and rust_labels.moved

    started = perf_counter()
    numpy_weight, numpy_bias = train_numpy(features, labels, epoch_count, learning_rate)
    numpy_ms = (perf_counter() - started) * 1_000

    started = perf_counter()
    python_weight, python_bias = train_python(
        feature_list, label_list, epoch_count, learning_rate
    )
    python_ms = (perf_counter() - started) * 1_000

    assert np.allclose([weight, bias], [numpy_weight, numpy_bias])
    assert np.allclose([weight, bias], [python_weight, python_bias])

    probability = 1.0 / (1.0 + np.exp(-(weight * features + bias)))
    accuracy = np.mean((probability >= 0.5) == labels)
    print(
        f"accuracy={accuracy:.1%} | Rust {rust_ms:.1f}ms | "
        f"NumPy {numpy_ms:.1f}ms | Python {python_ms:.1f}ms"
    )
    print(
        f"speedup: {numpy_ms / rust_ms:.1f}x vs NumPy, "
        f"{python_ms / rust_ms:.1f}x vs Python"
    )

    grid = np.linspace(-4.0, 4.0, 500)
    plt.scatter(
        features,
        labels,
        c=labels,
        cmap="coolwarm",
        alpha=0.35,
        edgecolors="none",
    )
    plt.plot(
        grid,
        1.0 / (1.0 + np.exp(-(weight * grid + bias))),
        color="black",
        linewidth=3,
    )
    plt.title("Logistic regression trained in Rust, plotted in Python")
    plt.xlabel("feature")
    plt.ylabel("P(class = 1)")
    plt.tight_layout()
    output_path = Path(__file__).with_name("ml_decision_curve.png")
    plt.savefig(output_path, dpi=160)
    plt.show()
