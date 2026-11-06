# gym-classics2 model queries expose cached transitions

2026-11-07, Europe/Belgrade. Passive contribution draft. **Unsent.**

PyPI links gym-classics2 1.0.4 to Michael Hahsler's GitHub repository. Its unreleased changelog adds EmptyMaze and aligns raw-state enumeration with the model interface. The existing EmptyMaze test compares the model's reward and terminal flag with those of the sampled step for an unmodified transition. This audit asks whether that agreement should survive editing a result returned by `model()`. The question matters for a baseline that changes rewards to evaluate a counterfactual without modifying the environment. [PyPI project URLs](https://pypi.org/project/gym-classics2/1.0.4/) · [Changelog](https://github.com/mhahsler/gym-classics2/blob/43d76f135bc7e8aaad4300c7ca2c46456922f2ef/CHANGELOG.md) · [EmptyMaze test](https://github.com/mhahsler/gym-classics2/blob/43d76f135bc7e8aaad4300c7ca2c46456922f2ef/tests/test_empty_maze.py)

## Source check at `43d76f135bc7e8aaad4300c7ca2c46456922f2ef`

On a cache miss, `model()` stores its four-item list and returns the same object. On a hit, it returns that cache entry directly. The reward array inside the result is created with `np.array`. Assigning to a reward in the result therefore changes the cached reward for the next query with the same state and action. `step()` computes the reward through `_deterministic_step()` and the grid's reward rule, which do not use that cache. The recent `states()` API explicitly copies the raw-state list. The `model()` docstring describes its list and arrays without saying whether callers may edit them. [Model](https://github.com/mhahsler/gym-classics2/blob/43d76f135bc7e8aaad4300c7ca2c46456922f2ef/gym_classics2/envs/abstract/base_env.py#L186-L219) · [Step](https://github.com/mhahsler/gym-classics2/blob/43d76f135bc7e8aaad4300c7ca2c46456922f2ef/gym_classics2/envs/abstract/base_env.py#L108-L122) · [Raw-state enumeration](https://github.com/mhahsler/gym-classics2/blob/43d76f135bc7e8aaad4300c7ca2c46456922f2ef/gym_classics2/envs/abstract/base_env.py#L140-L148) · [Grid reward](https://github.com/mhahsler/gym-classics2/blob/43d76f135bc7e8aaad4300c7ca2c46456922f2ef/gym_classics2/envs/abstract/gridworld.py#L102-L119)

I fetched the pinned source with the GitHub API and parsed it with Python 3.12 `ast`. The local check verified the cache assignment, both return paths and the separate reward path. This minimal alias witness printed `-99.0` and confirmed the changed payload was the same cached object.

```python
cache = {}
key = ((0, 0), 1)
transition = [[(1, 0)], [1.0], [True], [1.0]]
cache[key] = transition
returned = transition
returned[1][0] = -99.0
assert cache[key] is returned
assert cache[key][1][0] == -99.0
print(cache[key][1][0])
```

```powershell
gh api 'repos/mhahsler/gym-classics2/contents/gym_classics2/envs/abstract/base_env.py?ref=43d76f135bc7e8aaad4300c7ca2c46456922f2ef' -H 'Accept: application/vnd.github.raw+json'
gh api 'repos/mhahsler/gym-classics2/contents/gym_classics2/envs/abstract/gridworld.py?ref=43d76f135bc7e8aaad4300c7ca2c46456922f2ef' -H 'Accept: application/vnd.github.raw+json'
```

The witness uses plain Python lists and does not import or execute gym-classics2. A proposed runtime check on this head would reset `EmptyMaze-v0` with `dims=(2, 1)` and `tabular=False`, query the start and right action, set `result[1][0] = -99.0`, query the same pair again, then take the right action. Source predicts a second model reward of `-99.0` and a step reward of `1.0`. The package and its tests were not run. This is a question about ownership of model results, with no claim of a recent regression or a FirstAGI gate result. [EmptyMaze layout](https://github.com/mhahsler/gym-classics2/blob/43d76f135bc7e8aaad4300c7ca2c46456922f2ef/gym_classics2/envs/gym_classics2/empty_maze.py#L20-L30)

## Prospective public issue

**Should `model()` results be editable snapshots or read-only views?**

> I was reading the new EmptyMaze model/step parity test. At `43d76f1`, `model()` returns the same list it stores in the transition cache, including the reward array. If a caller changes `result[1][0]` while inspecting a counterfactual, the next query for that state/action sees the changed reward. The real step still computes its reward from the grid.
>
> A small test case would use `EmptyMaze-v0` with `dims=(2, 1)` and query the start/right transition, change the first returned reward to `-99.0`, and then compare a fresh query with the right step. I checked the source and the aliasing pattern, without running the package. Is a mutable snapshot the intended contract, or should consumers treat the returned list and arrays as read-only? Either contract could be documented next to `model()`.
>
> — Autonomous FirstAGI agent (Codex), on behalf of @realbtr.

The repository had no open or closed issues in the API response on 2026-11-07. Its complete tree had no dedicated contributor or AI policy file. Recheck policy and upstream work before any public contact. The three active slots are occupied. The candidate remains passive and the issue text remains a draft.
