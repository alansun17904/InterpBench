import argparse
import json
import os
import pickle
import torch
import random
from argparse import Namespace

import numpy as np
import torch as t
import wandb
from iit.utils.iit_dataset import train_test_split, IITDataset

from circuits_benchmark.benchmark.benchmark_case import BenchmarkCase
from circuits_benchmark.commands.common_args import add_common_args
from circuits_benchmark.transformers.hooked_tracr_transformer import HookedTracrTransformer
from circuits_benchmark.utils.circuit.edges_list import circuit_to_edges_list
from circuits_benchmark.utils.iit.iit_hl_model import IITHLModel


def setup_args_parser(subparsers):
    parser = subparsers.add_parser("iit")
    add_common_args(parser)

    # IIT training args
    parser.add_argument(
        "-iit", "--iit_weight", type=float, default=1.0, help="IIT weight"
    )
    parser.add_argument(
        "-b", "--behavior_weight", type=float, default=1.0, help="Behavior weight",
    )
    parser.add_argument(
        "-s", "--strict_weight", type=float, default=0.4, help="Strict weight"
    )
    parser.add_argument(
        "-single-loss", "--use-single-loss", action="store_true", help="Use single loss"
    )
    parser.add_argument(
        "--model-pair", choices=["freeze", "strict", "stop_grad"], default="strict"
    )
    parser.add_argument(
        "--same-size", action="store_true", help="Use same size for ll model"
    )

    parser.add_argument(
        "--epochs", type=int, default=2000, help="Number of epochs"
    )
    parser.add_argument(
        "--early-stop-accuracy-threshold", type=float, default=99.5, help="Early stop accuracy threshold"
    )
    parser.add_argument(
        "--batch-size", type=int, default=256, help="Batch size"
    )
    parser.add_argument(
        "--lr", type=float, default=1e-3, help="Learning rate"
    )
    parser.add_argument(
        "--clip-grad-norm", type=float, default=0.1, help="Clip grad norm"
    )
    parser.add_argument(
        "--num-samples", type=int, default=12000, help="Number of samples"
    )
    parser.add_argument(
        "--scheduler-val-metric", nargs="+", default=["val/accuracy", "val/IIA", "val/strict_accuracy"],
        help="Scheduler validation metrics"
    )
    parser.add_argument(
        "--siit-sampling", type=str, choices=["individual", "sample_all", "all"], default="individual",
        help="SIIT sampling mode"
    )
    parser.add_argument(
        "--val-iia-sampling", type=str, choices=["random", "all"], default="random",
        help="Val IIA sampling mode"
    )
    parser.add_argument(
        "--lr-scheduler", type=str, choices=["", "plateau", "linear"], default="", help="LR scheduler"
    )

    parser.add_argument(
        "--use-wandb", action="store_true", help="Use wandb"
    )
    parser.add_argument(
        "--wandb_entity", type=str, required=False, help="Wandb entity"
    )
    parser.add_argument(
        "--wandb-project", type=str, default="", help="Wandb project"
    )
    parser.add_argument(
        "--wandb-name", type=str, default="", help="Wandb name"
    )
    parser.add_argument(
        "--save-model-to-wandb", action="store_true", help="Save model to wandb"
    )

    parser.add_argument(
        "--sweep", action="store_true", help="Run a wandb sweep"
    )
    parser.add_argument(
        "--sweep-config-file", type=str, help="Sweep config file", default=None
    )
    parser.add_argument(
        "--backprop-on-cache", action="store_true", help="Don't detach while caching"
    )

    # IOI specific args
    parser.add_argument(
        "--include-mlp", action="store_true", help="Include MLP in IOI circuit"
    )

    # correspondence variation
    parser.add_argument(
        "--rand-correspondence", action="store_true", help="Varies hl-ll correspondence when creating ll model"
    )

    # architecture variation
    parser.add_argument(
        "--rand-architecture", action="store_true", help="Varies architecture when creating ll model"
    )


def config_is_bad(config):
    iit_weight = config.iit_weight
    behavior_weight = config.behavior_weight
    strict_weight = config.strict_weight

    if iit_weight == behavior_weight and behavior_weight == strict_weight:
        return True
    # reject any combination of [0, x, x]
    weights_tuple = (iit_weight, behavior_weight, strict_weight)
    if weights_tuple in [(0, x, x) for x in [0, 0.5, 1.5]] + [
        (x, 0, x) for x in [0, 0.5, 1.5]
    ] + [(x, x, 0) for x in [0, 0.5, 1.5]]:
        return True

    # reject any combination of [x, 0, 0]
    if weights_tuple in [(x, 0, 0) for x in [0, 0.5, 1.5]] + [
        (0, x, 0) for x in [0, 0.5, 1.5]
    ] + [(0, 0, x) for x in [0, 0.5, 1.5]]:
        return True

    return False


def run_iit_train(case: BenchmarkCase, args: Namespace):
    def main():
        wandb.init()
        if config_is_bad(wandb.config):
            return
        config = {
            **wandb.config,
            "use_wandb": True,
            "wandb_project": args.wandb_project,
            "wandb_name": args.wandb_name,
            "device": "cpu" if args.device == "cpu" else "cuda",
        }
        train_model(case, config)

    if args.sweep:
        sweep_config = {
            "name": "tracr_iit",
            "method": "grid",
            "parameters": {
                "atol": {"values": [0.05]},
                "lr": {"values": [1e-2, 1e-3, 1e-4, 1e-5]},
                "use_single_loss": {"values": [True, False]},
                "iit_weight": {"values": [0.4, 0.5, 0.6, 1.0]},
                "behavior_weight": {"values": [0.5, 1.0]},
                "strict_weight": {"values": [0.0, 0.2, 0.5, 1.0, 1.5]},
                "epochs": {"values": [args.epochs]},
                "early_stop_accuracy_threshold": {"values": [args.early_stop_accuracy_threshold]},
                "act_fn": {"values": ["relu", "gelu"]},
                "clip_grad_norm": {"values": [10, 1.0, 0.1, 0.05]},
                "lr_scheduler": {"values": ["plateau", ""]},
                "model_pair": {"values": ["freeze", "strict_iit", "stop_grad"]},
                "same_size": {"values": [args.same_size]},
                "seed": {"values": [args.seed]},
                "batch_size": {"values": [args.batch_size]},
                "include_mlp": {"values": [args.include_mlp]},
                "detach_while_caching": {"values": [not args.backprop_on_cache]},
                "scheduler_val_metric": {"values": [args.scheduler_val_metric]},
                "siit_sampling": {"values": [args.siit_sampling]},
                "val_iia_sampling": {"values": [args.val_iia_sampling]},
                "final_lr": {"values": [args.final_lr]},
            },
        }
        sweep_id = wandb.sweep(
            sweep_config,
            project=f"iit_{case.get_name()}",
            entity=args.wandb_entity,
        )
        wandb.agent(sweep_id, main)
    else:
        config = {
            "output_dir": args.output_dir,
            "atol": 0.05,
            "lr": args.lr,
            "use_single_loss": args.use_single_loss,
            "iit_weight": args.iit_weight,
            "behavior_weight": args.behavior_weight,
            "strict_weight": args.strict_weight,
            "epochs": args.epochs,
            "early_stop_accuracy_threshold": args.early_stop_accuracy_threshold,
            "act_fn": "gelu",
            "use_wandb": args.use_wandb,
            "wandb_project": args.wandb_project,
            "wandb_name": args.wandb_name,
            "save_model_to_wandb": args.save_model_to_wandb,
            "device": "cpu" if args.device == "cpu" else "cuda" if t.cuda.is_available() else "cpu",
            "clip_grad_norm": args.clip_grad_norm,
            "lr_scheduler": args.lr_scheduler,
            "model_pair": args.model_pair,
            "same_size": args.same_size,
            "seed": args.seed,
            "batch_size": args.batch_size,
            "include_mlp": args.include_mlp,
            "detach_while_caching": not args.backprop_on_cache,
            "scheduler_val_metric": args.scheduler_val_metric,
            "siit_sampling": args.siit_sampling,
            "val_iia_sampling": args.val_iia_sampling,
            "rand_correspondence": args.rand_correspondence,
            "rand_architecture": args.rand_architecture
        }

        args = argparse.Namespace(**config)
        model_pair = train_model(
            case, args
        )

        # save the model
        output_dir = args.output_dir
        save_dir = f"{output_dir}/"
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
        weight_int = int(
            args.iit_weight * 10
            + args.behavior_weight * 100
            + args.strict_weight * 1000
        )

        t.save(
            model_pair.ll_model.state_dict(),
            f"{save_dir}/ll_model_{weight_int}.pth",
        )

        # save training args, config
        with open(f"{save_dir}/meta_{weight_int}.json", "w") as f:
            json.dump(config, f)

        # Save the config
        ll_model_cfg = model_pair.ll_model.cfg
        ll_model_cfg_dict = ll_model_cfg.to_dict()

        pickle.dump(ll_model_cfg_dict, open(f"{save_dir}/ll_model_cfg_{weight_int}.pkl", "wb"))

        # Dump ground truth edges
        gt_circuit = case.get_ll_gt_circuit()
        edges_list = circuit_to_edges_list(gt_circuit)
        pickle.dump(edges_list, open(f"{save_dir}/edges.pkl", "wb"))

        # Save the correspondence between hl and ll
        pickle.dump(model_pair.corr, open(f"{save_dir}/hl_ll_corr.pkl", "wb"))

        if args.use_wandb:
            if args.save_model_to_wandb:
                wandb.save(f"{save_dir}/*", base_path=output_dir)
            wandb.finish()


def train_model(
    case: BenchmarkCase,
    args: Namespace,
):
    t.manual_seed(args.seed)
    np.random.seed(args.seed)
    random.seed(args.seed)

    lr_scheduler_map = {
        "": None,
        "plateau": t.optim.lr_scheduler.ReduceLROnPlateau,
        "linear": t.optim.lr_scheduler.LambdaLR
    }

    device = torch.device(args.device)

    training_args = {
        # generic training args
        "lr": args.lr,
        "batch_size": args.batch_size,
        "atol": args.atol,
        "clip_grad_norm": args.clip_grad_norm,
        "lr_scheduler": lr_scheduler_map[args.lr_scheduler],
        "early_stop": True,
        "early_stop_accuracy_threshold": args.early_stop_accuracy_threshold,
        # specific iit training args
        "behavior_weight": args.behavior_weight,
        "iit_weight": args.iit_weight,
        "strict_weight": args.strict_weight,
        "use_single_loss": args.use_single_loss,
        "detach_while_caching": args.detach_while_caching,
        "scheduler_val_metric": args.scheduler_val_metric,
        "siit_sampling": args.siit_sampling,
        "val_IIA_sampling": args.val_iia_sampling,
    }

    if args.lr_scheduler == "plateau":
        training_args["scheduler_kwargs"] = {
            "patience": 30,
            "factor": 0.5,
        }

    # GET LOW-LEVEL MODEL
    ll_model = case.get_ll_model(same_size=args.same_size, rand=args.rand_architecture, device=device)

    hl_model = case.get_hl_model(device=device)
    if isinstance(hl_model, HookedTracrTransformer):
        hl_model = IITHLModel(hl_model, eval_mode=False)
        hl_model.to(device)

    # GET CORRESPONDENCE
    hl_ll_corr = case.get_correspondence(
        include_mlp=args.include_mlp,
        same_size=args.same_size,
        rand=args.rand_correspondence,
        ll_model=ll_model,
    )

    model_pair = case.build_model_pair(
        training_args=training_args,
        ll_model=ll_model,
        hl_model=hl_model,
        hl_ll_corr=hl_ll_corr,
    )

    # prepare iit datasets for training and testing
    dataset = case.get_clean_data(min_samples=20000, max_samples=120_000, seed=args.seed)
    train_dataset, test_dataset = train_test_split(
        dataset, test_size=0.2, random_state=42
    )
    train_dataset = IITDataset(train_dataset, train_dataset, seed=args.seed, device=device)
    test_dataset = IITDataset(test_dataset, test_dataset, seed=args.seed, device=device)

    # train model
    print("Starting IIT training")
    model_pair.train(
        train_dataset,
        test_dataset,
        epochs=args.epochs,
        use_wandb=args.use_wandb,
        wandb_project=args.wandb_project,
        wandb_name=args.wandb_name,
    )
    print("Done training")

    return model_pair
