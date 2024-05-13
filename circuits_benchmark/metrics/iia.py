import typing
from functools import partial
from typing import Set, Optional, Literal

import torch as t
from jaxtyping import Float
from torch import Tensor
from tqdm import tqdm
from transformer_lens import ActivationCache
from transformer_lens.hook_points import HookPoint

from circuits_benchmark.benchmark.benchmark_case import BenchmarkCase
from circuits_benchmark.benchmark.case_dataset import CaseDataset
from circuits_benchmark.metrics.resampling_ablation_loss.intervention import regular_intervention_hook_fn
from circuits_benchmark.transformers.acdc_circuit_builder import get_full_acdc_circuit
from circuits_benchmark.transformers.circuit_node import CircuitNode
from circuits_benchmark.transformers.hooked_tracr_transformer import HookedTracrTransformer

AblationType = Literal["zero", "mean", "resample"]
ablation_types = list(typing.get_args(AblationType))


def regular_intervention_hook_fn(
    activation: Float[Tensor, ""],
    hook: HookPoint,
    corrupted_cache: ActivationCache = None,
    head_index: int = None
):
  """This hook just replaces the output with a corrupted output."""
  if head_index is None:
    return corrupted_cache[hook.name]
  else:
    activation[:, :, head_index] = corrupted_cache[hook.name][:, :, head_index]
    return activation


def evaluate_iia_on_all_ablation_types(
    case: BenchmarkCase,
    base_model: HookedTracrTransformer,
    hypothesis_model: HookedTracrTransformer,
    data_size: Optional[int] = 1_000):
  iia_evaluation_results = {}

  clean_data = case.get_clean_data(count=data_size)
  corrupted_data = case.get_corrupted_data(count=data_size)

  # run corrupted data on both models
  _, base_model_corrupted_cache = base_model.run_with_cache(corrupted_data.get_inputs())
  _, hypothesis_model_corrupted_cache = hypothesis_model.run_with_cache(corrupted_data.get_inputs())

  # run clean data on both models
  _, base_model_clean_cache = base_model.run_with_cache(clean_data.get_inputs())
  _, hypothesis_model_clean_cache = hypothesis_model.run_with_cache(clean_data.get_inputs())

  full_circuit = get_full_acdc_circuit(base_model.cfg.n_layers, base_model.cfg.n_heads)
  hl_circuit, ll_circuit, alignment = case.get_tracr_circuit(granularity="acdc_hooks")

  for node in set(full_circuit.nodes):
    node_str = str(node)
    iia_evaluation_results[node_str] = {
      "node": node_str,
      "hook_name": node.name,
      "head_index": node.index,
      "in_circuit": node in ll_circuit.nodes,
    }

  for ablation_type in ablation_types:
    results_by_node = evaluate_iia(
      case,
      base_model,
      hypothesis_model,
      clean_data,
      base_model_corrupted_cache,
      hypothesis_model_corrupted_cache,
      base_model_clean_cache,
      hypothesis_model_clean_cache,
      ablation_type=ablation_type
    )

    for node_str, result in results_by_node.items():
      iia_evaluation_results[node_str][f"iia_{ablation_type}"] = result

  return iia_evaluation_results

def evaluate_iia(case: BenchmarkCase,
                 base_model: HookedTracrTransformer,
                 hypothesis_model: HookedTracrTransformer,
                 clean_data: CaseDataset,
                 base_model_corrupted_cache: ActivationCache,
                 hypothesis_model_corrupted_cache: ActivationCache,
                 base_model_clean_cache: ActivationCache,
                 hypothesis_model_clean_cache: ActivationCache,
                 ablation_type: Optional[AblationType] = "resample"):
  """Run Interchange Intervention Accuracy to measure if a hypothesis model has the same circuit as a base model."""
  print(f"Running IIA evaluation for case {case.get_index()} using ablation type \"{ablation_type}\".")
  full_circuit = get_full_acdc_circuit(base_model.cfg.n_layers, base_model.cfg.n_heads)

  # evaluate all nodes in the full circuit
  results_by_node = {}
  all_nodes: Set[CircuitNode] = set(full_circuit.nodes)
  for node in tqdm(all_nodes):
    node_str = str(node)
    hook_name = node.name
    head_index = node.index

    # run clean data on both models, patching corrupted data where necessary
    base_model_hook_fn, hypothesis_model_hook_fn = build_hook_fns(hook_name, head_index,
                                                                  base_model_clean_cache,
                                                                  hypothesis_model_clean_cache,
                                                                  base_model_corrupted_cache,
                                                                  hypothesis_model_corrupted_cache,
                                                                  ablation_type=ablation_type)

    with base_model.hooks([(hook_name, base_model_hook_fn)]):
      base_model_logits = base_model(clean_data.get_inputs())

    with hypothesis_model.hooks([(hook_name, hypothesis_model_hook_fn)]):
      hypothesis_model_logits = hypothesis_model(clean_data.get_inputs())

    # compare the outputs of the two models
    if base_model.is_categorical():
      # use KL divergence
      base_model_logits = t.nn.functional.softmax(base_model_logits, dim=-1)
      hypothesis_model_logits = t.nn.functional.softmax(hypothesis_model_logits, dim=-1)

      node_kl_div = t.nn.functional.kl_div(
        base_model_logits.log(), hypothesis_model_logits, reduction="none", log_target=False
      ).sum(dim=-1).mean().item()

      results_by_node[node_str] = node_kl_div

    else:
      raise NotImplementedError("Only categorical models are supported for now")

  return results_by_node


def build_hook_fns(hook_name:str,
                   head_index: int,
                   base_model_clean_cache: ActivationCache,
                   hypothesis_model_clean_cache: ActivationCache,
                   base_model_corrupted_cache: ActivationCache,
                   hypothesis_model_corrupted_cache: ActivationCache,
                   ablation_type: Optional[AblationType] = "resample"):
  # decide which data we are going to use for the patching
  base_model_patching_data = {}
  hypothesis_model_patching_data = {}

  if ablation_type == "resample":
    base_model_patching_data[hook_name] = base_model_corrupted_cache[hook_name]
    hypothesis_model_patching_data[hook_name] = hypothesis_model_corrupted_cache[hook_name]

  elif ablation_type == "mean":
    # take mean over all inputs
    base_model_orig_shape = base_model_clean_cache[hook_name].shape
    hypothesis_model_orig_shape = hypothesis_model_clean_cache[hook_name].shape

    if len(base_model_orig_shape) == 3:
      base_model_patching_data[hook_name] = base_model_clean_cache[hook_name].mean(dim=0).repeat(base_model_orig_shape[0], 1, 1)
      hypothesis_model_patching_data[hook_name] = hypothesis_model_clean_cache[hook_name].mean(dim=0).repeat(hypothesis_model_orig_shape[0], 1, 1)
    else:
      base_model_patching_data[hook_name] = base_model_clean_cache[hook_name].mean(dim=0).repeat(base_model_orig_shape[0], 1, 1, 1)
      hypothesis_model_patching_data[hook_name] = hypothesis_model_clean_cache[hook_name].mean(dim=0).repeat(hypothesis_model_orig_shape[0], 1, 1, 1)

  elif ablation_type == "zero":
    base_model_patching_data[hook_name] = t.zeros_like(base_model_clean_cache[hook_name])
    hypothesis_model_patching_data[hook_name] = t.zeros_like(hypothesis_model_clean_cache[hook_name])

  else:
    raise ValueError(f"Unknown ablation type: {ablation_type}")

  # build the hook functions
  base_model_hook_fn = partial(regular_intervention_hook_fn, corrupted_cache=base_model_patching_data,
                               head_index=head_index)
  hypothesis_model_hook_fn = partial(regular_intervention_hook_fn, corrupted_cache=hypothesis_model_patching_data,
                                     head_index=head_index)
  return base_model_hook_fn, hypothesis_model_hook_fn
