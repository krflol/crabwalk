"""Unified FastAPI showcase for Crabwalk concurrency and native ML training."""

from math import exp
from time import perf_counter

import numpy as np
from fastapi import FastAPI, Query

from crabwalk import rust

# Both crates are resolved by Cargo when Crabwalk first compiles this package.
rayon = rust.crate("rayon", version="1.12.0")
libm = rust.crate("libm", version="0.2")
app = FastAPI(title="Crabwalk: Python outside, Rust inside", version="1.0")


@rust.fn
def parallel_sum(n: rust.u64) -> rust.u64:
    values: rust.Vec[rust.u64] = rust.Vec([])
    for value in range(n):
        values.push(value)
    return values.par_iter().copied().sum()


@rust.fn
def rayon_workers() -> rust.usize:
    return rayon.current_num_threads()


@rust.fn
def train_logistic(
    features: rust.Owned[rust.Vec[rust.f64]],
    labels: rust.Owned[rust.Vec[rust.f64]],
    sample_count: rust.f64,
    epochs: rust.usize,
    learning_rate: rust.f64,
) -> rust.Tuple[rust.f64, rust.f64]:
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


@app.get("/parallel")
async def parallel(n: int = Query(5_000_000, ge=0, le=20_000_000)):
    # async_call keeps eligible native work off FastAPI's event-loop thread.
    started = perf_counter()
    total = await rust.async_call(parallel_sum, n)
    elapsed_ms = (perf_counter() - started) * 1_000
    return {
        "sum": total,
        "correct": total == n * (n - 1) // 2,
        "rust_ms": round(elapsed_ms, 2),
        "rayon_workers": rayon_workers(),
        "gil_released": parallel_sum.__crabwalk__["gil_released"],
    }


@app.get("/ml")
def machine_learning(
    samples: int = Query(400, ge=50, le=2_000),
    epochs: int = Query(5_000, ge=100, le=20_000),
    learning_rate: float = Query(0.08, gt=0.0, le=1.0),
):
    rng = np.random.default_rng(7)
    features = np.linspace(-3.0, 3.0, samples) + rng.normal(0.0, 0.25, samples)
    labels = (features + rng.normal(0.0, 0.8, samples) > 0.0).astype(float)
    feature_list, label_list = features.tolist(), labels.tolist()
    rust_features = rust.Vec[rust.f64](feature_list)
    rust_labels = rust.Vec[rust.f64](label_list)

    started = perf_counter()
    weight, bias = train_logistic(
        rust_features,
        rust_labels,
        float(samples),
        epochs,
        learning_rate,
    )
    rust_ms = (perf_counter() - started) * 1_000

    started = perf_counter()
    numpy_weight, numpy_bias = train_numpy(features, labels, epochs, learning_rate)
    numpy_ms = (perf_counter() - started) * 1_000

    started = perf_counter()
    python_weight, python_bias = train_python(
        feature_list, label_list, epochs, learning_rate
    )
    python_ms = (perf_counter() - started) * 1_000

    agreement = np.allclose([weight, bias], [numpy_weight, numpy_bias])
    agreement = agreement and np.allclose([weight, bias], [python_weight, python_bias])
    probability = 1.0 / (1.0 + np.exp(-(weight * features + bias)))
    accuracy = float(np.mean((probability >= 0.5) == labels))
    return {
        "model": {"weight": round(weight, 4), "bias": round(bias, 4)},
        "accuracy": round(accuracy, 4),
        "training_updates": samples * epochs,
        "implementations_agree": bool(agreement),
        "timing_ms": {
            "rust": round(rust_ms, 2),
            "numpy": round(numpy_ms, 2),
            "python": round(python_ms, 2),
        },
        "speedup": {
            "vs_numpy": round(numpy_ms / rust_ms, 1),
            "vs_python": round(python_ms / rust_ms, 1),
        },
        "ownership": {
            "features_moved": rust_features.moved,
            "labels_moved": rust_labels.moved,
        },
        "rust_crate": "libm 0.2",
    }


if __name__ == "__main__":
    import uvicorn

    # Port 8001 avoids the focused FastAPI example's default port 8000.
    uvicorn.run(app, host="127.0.0.1", port=8001)
