from argparse import Namespace
from typing import Literal

import numpy as np
import torch as t
from iit.model_pairs.base_model_pair import BaseModelPair
from iit.utils import IITDataset
from iit.utils.eval_ablations import (
    check_causal_effect,
    get_causal_effects_for_all_nodes,
    make_combined_dataframe_of_results,
    save_result,
    Categorical_Metric,
)

from circuits_benchmark.benchmark.benchmark_case import BenchmarkCase
from circuits_benchmark.commands.common_args import add_common_args, add_evaluation_common_ags
from circuits_benchmark.transformers.hooked_tracr_transformer import (
    HookedTracrTransformer,
)
from circuits_benchmark.utils.iit.iit_hl_model import IITHLModel
from circuits_benchmark.utils.ll_model_loader.ll_model_loader_factory import get_ll_model_loader_from_args


def setup_args_parser(subparsers):
    parser = subparsers.add_parser("iit")
    add_common_args(parser)
    add_evaluation_common_ags(parser)

    parser.add_argument("-m", "--mean", type=int, default=1, help="Use mean cache")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=512,
        help="Batch size for making mean cache (if using mean ablation)",
    )
    parser.add_argument(
        "--categorical-metric",
        choices=["accuracy", "kl_div", "kl_div_self"],
        default="accuracy",
        help="Categorical metric to use",
    )
    parser.add_argument(
        "--max-len", type=int, default=18000, help="Max length of unique data"
    )

    parser.add_argument(
        "--next-token", action="store_true", help="Use next token model"
    )
    parser.add_argument(
        "--include-mlp", action="store_true", help="Evaluate group 'with_mlp'"
    )

    parser.add_argument(
        "--use-wandb", action="store_true", help="Use wandb for logging"
    )
    parser.add_argument(
        "--wandb-project", type=str, default=None, help="Wandb project to log to"
    )
    parser.add_argument(
        "--wandb-name", type=str, default=None, help="Wandb name to log to"
    )


def get_node_effects(
    case: BenchmarkCase,
    model_pair: BaseModelPair,
    use_mean_cache: bool,
    individual_nodes: bool = True,
    seed: int = 42,
    max_len: int = 18000,
    batch_size: int = 512,
    categorical_metric: Literal["accuracy", "kl_div", "kl_div_self"] = "accuracy",
):
    np.random.seed(seed)
    t.manual_seed(seed)

    unique_dataset = case.get_clean_data(max_samples=max_len, unique_data=True)
    test_set = IITDataset(unique_dataset, unique_dataset, every_combination=True)

    with t.no_grad():
        result_not_in_circuit = check_causal_effect(
            model_pair,
            test_set,
            node_type="n",
            categorical_metric=Categorical_Metric(categorical_metric),
            verbose=False,
        )
        result_in_circuit = check_causal_effect(
            model_pair,
            test_set,
            node_type="c" if not individual_nodes else "individual_c",
            categorical_metric=Categorical_Metric(categorical_metric),
            verbose=False,
        )

        metric_collection = model_pair._run_eval_epoch(
            test_set.make_loader(batch_size, 0), model_pair.loss_fn
        )

        # zero/mean ablation
        za_result_not_in_circuit, za_result_in_circuit = (
            get_causal_effects_for_all_nodes(
                model_pair,
                unique_dataset,
                batch_size=len(unique_dataset),
                use_mean_cache=use_mean_cache,
            )
        )

    df = make_combined_dataframe_of_results(
        result_not_in_circuit,
        result_in_circuit,
        za_result_not_in_circuit,
        za_result_in_circuit,
        use_mean_cache=use_mean_cache,
    )
    return df, metric_collection


def run_iit_eval(case: BenchmarkCase, args: Namespace):
    output_dir = args.output_dir
    use_mean_cache = args.mean

    hl_model = case.get_hl_model()
    if isinstance(hl_model, HookedTracrTransformer):
        hl_model = IITHLModel(hl_model, eval_mode=True)

    ll_model_loader = get_ll_model_loader_from_args(case, args)
    hl_ll_corr, ll_model = ll_model_loader.load_ll_model_and_correspondence(args.device, output_dir=output_dir,
                                                                            same_size=args.same_size)
    ll_model.eval()
    ll_model.requires_grad_(False)

    model_pair = case.build_model_pair(hl_model=hl_model, ll_model=ll_model, hl_ll_corr=hl_ll_corr)
    df, metric_collection = get_node_effects(
        case,
        model_pair,
        use_mean_cache,
        seed=args.seed,
        max_len=args.max_len,
        batch_size=args.batch_size,
        categorical_metric=args.categorical_metric,
    )

    save_dir = f"{output_dir}/ll_models/{case.get_name()}/results_{ll_model_loader.get_output_suffix()}"
    suffix = f"_{args.categorical_metric}" if hl_model.is_categorical() else ""
    save_result(df, save_dir, model_pair, suffix=suffix)
    with open(f"{save_dir}/metric_collection.log", "w") as f:
        f.write(str(metric_collection))
        print(metric_collection)

    if args.use_wandb:
        import wandb

        wandb_project = args.wandb_project
        if wandb_project is None:
            wandb_project = f"node_effect{'_same_size' if args.same_size else ''}"

        wandb_name = args.wandb_name
        if wandb_name is None:
            wandb_name = f"case_{case.get_name()}_{ll_model_loader.get_output_suffix()}{suffix}"

        wandb.init(
            project=wandb_project,
            name=wandb_name,
            tags=[
                f"case_{case.get_name()}",
                f"{ll_model_loader.get_output_suffix()}",
                f"metric{suffix}",
            ],
        )
        wandb.log(metric_collection.to_dict())
        wandb.save(f"{output_dir}/ll_models/{case.get_name()}/*")
        wandb.save(f"{save_dir}/*")
        wandb.finish()
