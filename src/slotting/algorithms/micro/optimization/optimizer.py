from __future__ import annotations

from dataclasses import dataclass
import math
import random
import time

from slotting.algorithms.micro.kpi_state import HybridKpiState, Move, RelocateMove, SwapMove


@dataclass(frozen=True)
class LocalSearchConfig:
    iterations: int = 10_000
    time_budget_ms: int | None = None
    seed: int = 0
    allow_annealing: bool = True
    temp_start: float = 1.0
    temp_end: float = 0.01
    log_every: int = 500
    log_path: str | None = None
    trace_path: str | None = None


@dataclass(frozen=True)
class OptimizationResult:
    initial_kpi: float
    final_kpi: float
    best_kpi: float
    iterations: int
    accepts: int
    rejects: int


def optimize(
    state: HybridKpiState,
    config: LocalSearchConfig,
) -> OptimizationResult:
    rng = random.Random(config.seed)
    start_time = time.time()

    initial_kpi = state.global_kpi
    best_kpi = initial_kpi
    accepts = 0
    rejects = 0
    reject_reasons: dict[str, int] = {}
    logger, close_logger = _build_logger(config)

    idx = 0
    while idx < config.iterations:
        if _should_stop(start_time, config):
            break
        accept, temp, reason = _run_iteration(state, config, rng, idx)
        if accept is None:
            rejects += 1
            if reason:
                reject_reasons[reason] = reject_reasons.get(reason, 0) + 1
        elif accept:
            accepts += 1
            if state.global_kpi > best_kpi:
                best_kpi = state.global_kpi
        else:
            rejects += 1

        if config.log_every > 0 and (idx + 1) % config.log_every == 0:
            logger(idx + 1, state.global_kpi, best_kpi, accepts, rejects, temp)
            _log_reject_reasons(reject_reasons)
        idx += 1

    if config.log_path or config.trace_path:
        logger(
            idx + 1,
            state.global_kpi,
            best_kpi,
            accepts,
            rejects,
            _temperature(config, max(idx, 0), config.iterations),
        )
        _log_reject_reasons(reject_reasons)

    result = OptimizationResult(
        initial_kpi=initial_kpi,
        final_kpi=state.global_kpi,
        best_kpi=best_kpi,
        iterations=idx + 1,
        accepts=accepts,
        rejects=rejects,
    )
    close_logger()
    return result


def _sample_move(state: HybridKpiState, rng: random.Random) -> Move:
    subgroup_ids = state.subgroup_ids()
    if len(subgroup_ids) < 2:
        return SwapMove(sku_a="", sku_b="")

    movable_from = [sg for sg in subgroup_ids if state.subgroup_size(sg) > 1]
    movable_to = [sg for sg in subgroup_ids if state.subgroup_size(sg) < state.max_subgroup_size()]

    # Prefer relocate only when feasible
    if movable_from and movable_to and rng.random() < 0.5:
        sg_from_id = rng.choice(movable_from)
        sg_to_id = rng.choice([sg for sg in movable_to if sg != sg_from_id])
        sku_id = rng.choice(state.subgroup_skus(sg_from_id))
        return RelocateMove(
            sku_id=sku_id, from_subgroup_id=sg_from_id, to_subgroup_id=sg_to_id
        )

    sg_a_id, sg_b_id = rng.sample(subgroup_ids, 2)
    sku_a = rng.choice(state.subgroup_skus(sg_a_id))
    sku_b = rng.choice(state.subgroup_skus(sg_b_id))
    return SwapMove(sku_a=sku_a, sku_b=sku_b)


def _temperature(config: LocalSearchConfig, idx: int, total: int) -> float:
    if total <= 1:
        return config.temp_end
    frac = idx / (total - 1)
    return config.temp_start + (config.temp_end - config.temp_start) * frac


def _should_accept(
    delta: float,
    temp: float,
    allow_annealing: bool,
    rng: random.Random,
) -> bool:
    if delta > 0:
        return True
    if not allow_annealing or temp <= 0:
        return False
    accept_prob = math.exp(delta / temp)
    return rng.random() < accept_prob


def _should_stop(start_time: float, config: LocalSearchConfig) -> bool:
    if config.time_budget_ms is None:
        return False
    elapsed_ms = (time.time() - start_time) * 1000.0
    return elapsed_ms >= config.time_budget_ms


def _run_iteration(
    state: HybridKpiState,
    config: LocalSearchConfig,
    rng: random.Random,
    idx: int,
) -> tuple[bool | None, float, str | None]:
    move = _sample_move(state, rng)
    preview = state.preview_move(move)
    if not preview.is_valid:
        reason = preview.reasons[0] if preview.reasons else "invalid_move"
        return None, _temperature(config, idx, config.iterations), reason
    delta = preview.delta_global_kpi
    temp = _temperature(config, idx, config.iterations)
    accept = _should_accept(delta, temp, config.allow_annealing, rng)
    if accept:
        state.apply_move(move)
    return accept, temp, None


def _log_reject_reasons(reject_reasons: dict[str, int]) -> None:
    if not reject_reasons:
        return
    top = sorted(reject_reasons.items(), key=lambda item: item[1], reverse=True)[:5]
    summary = ", ".join(f"{reason}={count}" for reason, count in top)
    print(f"reject_reasons(top5): {summary}")


def _build_logger(config: LocalSearchConfig):
    log_handle = open(config.log_path, "a", encoding="utf-8") if config.log_path else None
    trace_handle = open(config.trace_path, "w", encoding="utf-8") if config.trace_path else None
    if trace_handle is not None:
        trace_handle.write("iter,current_kpi,best_kpi,accepts,rejects,temp\n")

    def _log(iteration: int, current: float, best: float, accepts: int, rejects: int, temp: float) -> None:
        line = (
            f"iter={iteration} current={current:.6f} best={best:.6f} "
            f"accepts={accepts} rejects={rejects} temp={temp:.6f}"
        )
        print(line)
        if log_handle is not None:
            log_handle.write(line + "\n")
            log_handle.flush()
        if trace_handle is not None:
            trace_handle.write(
                f"{iteration},{current:.6f},{best:.6f},{accepts},{rejects},{temp:.6f}\n"
            )
            trace_handle.flush()

    def _close() -> None:
        if log_handle is not None:
            log_handle.close()
        if trace_handle is not None:
            trace_handle.close()

    return _log, _close
