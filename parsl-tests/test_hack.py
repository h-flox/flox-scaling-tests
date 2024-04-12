
import argparse
import time
import torch
import flox
from parsl.addresses import address_by_interface

from pathlib import Path

from torch import nn
from torch.nn import functional as F
from torchvision import transforms
from torchvision.datasets import FashionMNIST
from torchvision.models import squeezenet1_0

from flox.data.utils import federated_split
from flox.flock.factory import create_standard_flock
from flox.nn import FloxModule

import parsl
from parsl.app.app import python_app, bash_app
from parsl.config import Config
from parsl.launchers import SrunLauncher
from parsl.providers import SlurmProvider, LocalProvider
from parsl.executors import HighThroughputExecutor

from torchvision.models import alexnet, resnet18, resnet50, resnet152
from flox_classes import Net, KyleNet


def main(args: argparse.Namespace):
    
    flock = create_standard_flock(num_workers=args.max_workers)
    root_dir = Path(args.root_dir)
    if "~" in str(root_dir):
        root_dir = root_dir.expanduser()
    data = FashionMNIST(
        root=str(root_dir),
        download=False,
        train=True,
        transform=transforms.Compose(
            [
                transforms.ToTensor(),
                transforms.Normalize(0.5, 0.5),
            ]
        ),
    )
    fed_data = federated_split(
        data,
        flock,
        num_classes=10,
        labels_alpha=args.labels_alpha,
        samples_alpha=args.samples_alpha,
    )

    parsl_local = {
        "label": "local-htex",
        "max_workers_per_node": args.max_workers,
        "provider": LocalProvider(
            worker_init="source ~/setup_parsl_test_env.v2.sh; export PYTHONPATH=/home/yadunand/flox-scaling-tests/parsl-tests:$PYTHONPATH"
        ),
    }
    parsl_remote = {
        "label": "expanse-htex",
        # Provision 128 workers per node, and get multiple nodes to reach required # of workers
        "max_workers_per_node": min(128, args.max_workers),
        "provider": LocalProvider(
            launcher=SrunLauncher(overrides="--exclude=$SLURMD_NODENAME"),
            worker_init="source ~/setup_parsl_test_env.sh; export PYTHONPATH=/home/yadunand/flox-scaling-tests/parsl-tests:$PYTHONPATH",
            init_blocks=1,
        ),
    }
    if args.config == "multinode":
        parsl_config = parsl_remote
    else:
        parsl_config = parsl_local
    print(f"Selecting parsl_config: {parsl_config}")

    flox_model = None
    if args.model == 0:
        flox_model = None
    elif args.model == 1:
        flox_model = KyleNet()
    elif args.model == 3:
        flox_model = squeezenet1_0(weights=None)
    elif args.model == 18:
        flox_model = resnet18(weights=None)
    elif args.model == 50:
        flox_model = resnet50(weights=None)
    elif args.model == 152:
        flox_model = resnet152(weights=None)

    flox.federated_fit(
        flock=flock,
        module=flox_model,
        # datasets=fed_data,
        datasets=None,
        num_global_rounds=args.rounds,
        strategy="fedsgd",
        kind="sync-v2",
        debug_mode=True,
        launcher_kind=args.executor,
        launcher_cfg=parsl_config,
    )


if __name__ == "__main__":
    args = argparse.ArgumentParser()
    args.add_argument(
        "--executor",
        "-e",
        type=str,
        choices=["process", "thread", "parsl", "globus-compute"],
        default="parsl",
    )
    args.add_argument(
        "--config",
        type=str,
        choices=["singlenode", "multinode"],
        default="singlenode",
    )
    args.add_argument("--max_workers", "-w", type=int,
                      help="This is the # of parsl workers and flox worker_nodes we get",
                      default=1)
    args.add_argument("--samples_alpha", "-s", type=float, default=1000.0)
    args.add_argument("--labels_alpha", "-l", type=float, default=1000.0)
    args.add_argument("--rounds", "-r", type=int, default=1)
    args.add_argument("--root_dir", "-d", type=str, default=".")
    args.add_argument(
        "--model",
        choices=[0, 1, 3, 18, 50, 152],
        required=True,
        type=int,
        help="Model: 0 - 1 layer, 1 KyleNet, Resnet 18, 50, 152",
    )
    parsed_args = args.parse_args()
    assert parsed_args.samples_alpha > 0.0
    assert parsed_args.labels_alpha > 0.0
    start_time = time.perf_counter()
    print(f"start:{start_time}")
    main(parsed_args)
    end_time = time.perf_counter()
    print(f"end:{end_time}")
    print(f"❯ Finished in {end_time - start_time} seconds.")
