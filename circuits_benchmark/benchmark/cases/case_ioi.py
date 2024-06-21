from typing import Optional, Callable

import torch as t
from jaxtyping import Float
from torch import Tensor
from torch.utils.data import Dataset
from transformer_lens import HookedTransformer
from transformer_lens.hook_points import HookedRootModule

from circuits_benchmark.benchmark.benchmark_case import BenchmarkCase
from circuits_benchmark.benchmark.case_dataset import CaseDataset
from iit.tasks.ioi import ioi_cfg, IOI_HL, NAMES, IOIDatasetWrapper, make_corr_dict, suffixes
from iit.utils.correspondence import Correspondence


class CaseIOI(BenchmarkCase):
  def __init__(self):
    self.ll_model = None
    self.hl_model = None

  def get_task_description(self) -> str:
    """Returns the task description for the benchmark case."""
    return "Indirect Object Identification (IOI) task."

  def get_clean_data(self,
                     min_samples: Optional[int] = 10,
                     max_samples: Optional[int] = 10,
                     seed: Optional[int] = 42,
                     unique_data: Optional[bool] = False) -> CaseDataset:
    ll_model = self.get_ll_model()
    ioi_dataset = IOIDatasetWrapper(
      num_samples=max_samples,
      tokenizer=ll_model.tokenizer,
      names=NAMES,
    )
    # We need to change IOIDatasetWrapper to inherit from CaseDataset if we want to remove the type ignore below
    return ioi_dataset  # type: ignore

  def get_corrupted_data(self,
                         min_samples: Optional[int] = 10,
                         max_samples: Optional[int] = 10,
                         seed: Optional[int] = 43,
                         unique_data: Optional[bool] = False) -> CaseDataset:
    return self.get_clean_data(min_samples=min_samples, max_samples=max_samples, seed=seed, unique_data=unique_data)

  def get_validation_metric(self) -> Callable[[Tensor], Float[Tensor, ""]]:
    """Returns the validation metric for the benchmark case."""
    raise NotImplementedError()

  def get_ll_model(
      self,
      device: t.device = t.device("cuda") if t.cuda.is_available() else t.device("cpu"),
      *args, **kwargs
  ) -> HookedTransformer:
    """Returns the untrained transformer_lens model for this case.
    In IIT terminology, this is the LL model before training."""
    if self.ll_model is not None:
      return self.ll_model

    ll_cfg = HookedTransformer.from_pretrained(
      "gpt2"
    ).cfg.to_dict()
    ll_cfg.update(ioi_cfg)

    ll_cfg["init_weights"] = True
    self.ll_model = HookedTransformer(ll_cfg).to(device)

    return self.ll_model

  def get_hl_model(
      self,
      device: t.device = t.device("cuda") if t.cuda.is_available() else t.device("cpu"),
      *args, **kwargs
  ) -> HookedRootModule:
    """Builds the transformer_lens reference model for this case.
    In IIT terminology, this is the HL model."""
    if self.hl_model is not None:
      return self.hl_model

    ll_model = self.get_ll_model()
    names = t.tensor([ll_model.tokenizer.encode(name)[0] for name in NAMES]).to(device)
    self.hl_model = IOI_HL(d_vocab=ll_model.cfg.d_vocab_out, names=names).to(device)

    return self.hl_model

  def get_correspondence(self, include_mlp: bool = False, *args, **kwargs) -> Correspondence:
    """Returns the correspondence between the reference and the benchmark model."""
    corr_dict = make_corr_dict(include_mlp=include_mlp)
    return Correspondence.make_corr_from_dict(corr_dict, suffixes=suffixes)
