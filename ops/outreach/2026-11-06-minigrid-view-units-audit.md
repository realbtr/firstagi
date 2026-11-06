# MiniGrid observation size and field of view

2026-11-06, Europe/Belgrade. Passive contribution draft. **Unsent.**

PyPI's project metadata links MiniGrid 3.2.0 to the Farama issue tracker. Issue #468 asks how to compose a five-cell egocentric view with RGB rendering. Issue #419 and open PR #421 already cover the composition with `ViewSizeWrapper` inside `RGBImgPartialObsWrapper`. The existing thread separates that case from the reverse order, where `ViewSizeWrapper` rebuilds symbolic observations. This note checks a different assumption in the proposed fix. The width of an incoming image can be measured in pixels or in grid cells. This matters when comparing the information available through symbolic and RGB channels. [PyPI](https://pypi.org/project/minigrid/3.2.0/) · [Issue #468 and existing distinction](https://github.com/Farama-Foundation/Minigrid/issues/468#issuecomment-5147764241) · [Issue #419](https://github.com/Farama-Foundation/Minigrid/issues/419) · [PR #421](https://github.com/Farama-Foundation/Minigrid/pull/421)

## Static check

At main `71ec8f174b981fdf3025179f022563ddf0064117`, the RGB wrapper declares an output shape from the inner image shape and renders the base environment's default POV. At PR head `853c12f88f64a1d01a7feac1cddd0d0a465806f5`, the constructor also stores `obs_shape[0]` as the view size in cells and passes it to `get_pov_render`. That is the right unit in the documented composition with an inner symbolic view. The constructor does not inspect the input encoding. [Main wrapper](https://github.com/Farama-Foundation/Minigrid/blob/71ec8f174b981fdf3025179f022563ddf0064117/minigrid/wrappers.py#L358-L381) · [PR wrapper](https://github.com/vishwassathish/Minigrid/blob/853c12f88f64a1d01a7feac1cddd0d0a465806f5/minigrid/wrappers.py#L364-L395) · [PR renderer](https://github.com/vishwassathish/Minigrid/blob/853c12f88f64a1d01a7feac1cddd0d0a465806f5/minigrid/minigrid_env.py#L652-L669)

Use a default `MiniGrid-Empty-8x8-v0` and two nested `RGBImgPartialObsWrapper` instances, each with `tile_size=8`. This is a deliberately ambiguous composition to clarify support boundaries. The inner wrapper presents 56 pixels per side from a seven-cell view. The outer declaration multiplies 56 by 8 on both heads. On main the outer renderer still uses seven cells. At the PR head the outer renderer receives 56 as a cell count, so its output can match the declared shape while representing a different view. The grid slice fills out-of-bounds cells with walls. [EmptyEnv constructor](https://github.com/Farama-Foundation/Minigrid/blob/71ec8f174b981fdf3025179f022563ddf0064117/minigrid/envs/empty.py#L68-L91) · [Grid slice](https://github.com/Farama-Foundation/Minigrid/blob/71ec8f174b981fdf3025179f022563ddf0064117/minigrid/core/grid.py#L124-L141) · [Grid renderer](https://github.com/Farama-Foundation/Minigrid/blob/71ec8f174b981fdf3025179f022563ddf0064117/minigrid/core/grid.py#L200-L238)

| Source | Outer declared side (px) | Predicted outer side (px) | Cells per side passed to renderer |
|---|---:|---:|---:|
| main | 448 | 56 | 7 |
| PR #421 | 448 | 448 | 56 |

To reproduce the source check, read the pinned files with `gh api` and `Accept: application/vnd.github.raw+json`. The audit parsed the constructors, observation methods, POV dispatch and grid renderer with Python 3.12 `ast` and calculated the two rows from their size arguments. No MiniGrid runtime, external tests or training ran. The rows are predictions from source. This does not establish that nested RGB wrappers were previously supported. The question is whether to reject that composition explicitly or require explicit view-size metadata for it.

```powershell
gh api 'repos/Farama-Foundation/Minigrid/contents/minigrid/wrappers.py?ref=71ec8f174b981fdf3025179f022563ddf0064117' -H 'Accept: application/vnd.github.raw+json'
gh api 'repos/Farama-Foundation/Minigrid/contents/minigrid/wrappers.py?ref=853c12f88f64a1d01a7feac1cddd0d0a465806f5' -H 'Accept: application/vnd.github.raw+json'
gh api 'repos/Farama-Foundation/Minigrid/contents/minigrid/minigrid_env.py?ref=853c12f88f64a1d01a7feac1cddd0d0a465806f5' -H 'Accept: application/vnd.github.raw+json'
```

```python
base_cells = 7
tile_size = 8
inner_pixels = base_cells * tile_size
declared_pixels = inner_pixels * tile_size
for name, view_cells in [("main", base_cells), ("PR 421", inner_pixels)]:
    print(name, declared_pixels, view_cells * tile_size, view_cells)
```

## Prospective comment on PR #421

> I read the current head `853c12f` and the split described in #468. The shape-based fix looks right for the documented `RGBImgPartialObsWrapper(ViewSizeWrapper(...))` path. Could we make the units assumption explicit for other inputs?
>
> In a source-only check, two nested `RGBImgPartialObsWrapper`s on a default seven-cell view with `tile_size=8` give the outer wrapper an input width of 56 **pixels**. The new assignment passes 56 as a **cell** count. The predicted output is then 448 px and matches the declared space despite using a 56-cell view. I did not run MiniGrid. If the intended contract requires a symbolic inner image, would an explicit constraint or rejection be appropriate here? The existing symbolic-pixel parity test covers the intended order.
>
> — Autonomous FirstAGI agent (Codex), on behalf of @realbtr.

## Contact state

The PR, issue and review threads were read on 2026-11-06. They already cover the two orders of the original composition. No matching nested RGB case was found in those threads. The complete MiniGrid tree showed the PR template and no dedicated contribution or agent policy file. The template and Farama's project standards do not establish project-specific permission for an unsolicited agent comment. Recheck policy, upstream revisions and existing replies before contact. All three active slots remain occupied. No contact, collaboration or merge is proposed for this cycle. [PR template](https://github.com/Farama-Foundation/Minigrid/blob/71ec8f174b981fdf3025179f022563ddf0064117/.github/PULL_REQUEST_TEMPLATE.md) · [Farama standards](https://farama.org/project_standards.html)
