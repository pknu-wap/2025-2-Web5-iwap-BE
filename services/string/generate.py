import argparse
from dataclasses import dataclass
from math import atan2
from time import time
from typing import List, Optional, Sequence, Tuple

import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import numpy as np
from skimage.draw import ellipse_perimeter, line_aa
from skimage.transform import resize


@dataclass
class StringArtOptions:
    side_len: int = 300
    export_strength: float = 0.1
    pull_amount: Optional[int] = None
    random_nails: Optional[int] = None
    radius1_multiplier: float = 1.0
    radius2_multiplier: float = 1.0
    nail_step: int = 4
    wb: bool = False
    rgb: bool = False
    rect: bool = False


@dataclass
class StringArtResult:
    image: np.ndarray
    mode: str
    pull_orders: List[List[int]]
    nails: List[Tuple[int, int]]
    scaled_nails: List[Tuple[int, int]]
    options: StringArtOptions


def rgb2gray(rgb: np.ndarray) -> np.ndarray:
    return np.dot(rgb[..., :3], [0.2989, 0.5870, 0.1140])


def largest_square(image: np.ndarray) -> np.ndarray:
    short_edge = np.argmin(image.shape[:2])
    short_edge_half = image.shape[short_edge] // 2
    long_edge_center = image.shape[1 - short_edge] // 2
    if short_edge == 0:
        return image[:, long_edge_center - short_edge_half : long_edge_center + short_edge_half]
    if short_edge == 1:
        return image[long_edge_center - short_edge_half : long_edge_center + short_edge_half, :]
    return image


def create_rectangle_nail_positions(shape: Sequence[int], nail_step: int = 2) -> np.ndarray:
    height, width = shape
    nails_top = [(0, i) for i in range(0, width, nail_step)]
    nails_bot = [(height - 1, i) for i in range(0, width, nail_step)]
    nails_right = [(i, width - 1) for i in range(1, height - 1, nail_step)]
    nails_left = [(i, 0) for i in range(1, height - 1, nail_step)]
    nails = nails_top + nails_right + nails_bot + nails_left
    return np.asarray(nails)


def create_circle_nail_positions(
    shape: Sequence[int],
    nail_step: int = 2,
    r1_multip: float = 1.0,
    r2_multip: float = 1.0,
) -> np.ndarray:
    height, width = shape
    centre = (height // 2, width // 2)
    radius = min(height, width) // 2 - 1
    rr, cc = ellipse_perimeter(centre[0], centre[1], int(radius * r1_multip), int(radius * r2_multip))
    nails = list({(int(rr[i]), int(cc[i])) for i in range(len(cc))})
    nails.sort(key=lambda c: atan2(c[0] - centre[0], c[1] - centre[1]))
    nails = nails[::nail_step]
    return np.asarray(nails)


def init_canvas(shape: Sequence[int], black: bool = False) -> np.ndarray:
    return np.zeros(shape) if black else np.ones(shape)


def get_aa_line(from_pos, to_pos, str_strength, picture):
    rr, cc, val = line_aa(from_pos[0], from_pos[1], to_pos[0], to_pos[1])
    line = picture[rr, cc] + str_strength * val
    line = np.clip(line, a_min=0, a_max=1)
    return line, rr, cc


def find_best_nail_position(
    current_position,
    nails,
    str_pic,
    orig_pic,
    str_strength,
    random_nails: Optional[int] = None,
    rng: Optional[np.random.Generator] = None,
):
    best_cumulative_improvement = -99999
    best_nail_position = None
    best_nail_idx = None

    if random_nails:
        rng = rng or np.random.default_rng()
        sample_size = min(random_nails, len(nails))
        nail_ids = rng.choice(len(nails), size=sample_size, replace=False)
        nails_and_ids = ((idx, nails[idx]) for idx in nail_ids)
    else:
        nails_and_ids = enumerate(nails)

    for nail_idx, nail_position in nails_and_ids:
        overlayed_line, rr, cc = get_aa_line(current_position, nail_position, str_strength, str_pic)
        before_overlayed_line_diff = np.abs(str_pic[rr, cc] - orig_pic[rr, cc]) ** 2
        after_overlayed_line_diff = np.abs(overlayed_line - orig_pic[rr, cc]) ** 2
        cumulative_improvement = np.sum(before_overlayed_line_diff - after_overlayed_line_diff)

        if cumulative_improvement >= best_cumulative_improvement:
            best_cumulative_improvement = cumulative_improvement
            best_nail_position = nail_position
            best_nail_idx = nail_idx

    return best_nail_idx, best_nail_position, best_cumulative_improvement


def create_art(
    nails,
    orig_pic,
    str_pic,
    str_strength,
    i_limit: Optional[int] = None,
    random_nails: Optional[int] = None,
    rng: Optional[np.random.Generator] = None,
):
    start = time()
    iter_times = []

    current_position = nails[0]
    pull_order = [0]

    i = 0
    fails = 0
    while True:
        start_iter = time()
        i += 1

        if i_limit is None:
            if fails >= 3:
                break
        else:
            if i > i_limit:
                break

        idx, best_nail_position, best_cumulative_improvement = find_best_nail_position(
            current_position,
            nails,
            str_pic,
            orig_pic,
            str_strength,
            random_nails=random_nails,
            rng=rng,
        )

        if best_cumulative_improvement is None or best_cumulative_improvement <= 0:
            fails += 1
            continue

        pull_order.append(idx)
        best_overlayed_line, rr, cc = get_aa_line(current_position, best_nail_position, str_strength, str_pic)
        str_pic[rr, cc] = best_overlayed_line

        current_position = best_nail_position
        iter_times.append(time() - start_iter)

    if iter_times:
        avg_iter = np.mean(iter_times)
    else:
        avg_iter = 0.0

    print(f"Time: {time() - start:.3f}s, Avg iteration time: {avg_iter:.6f}s")
    return pull_order


def scale_nails(x_ratio, y_ratio, nails):
    return [(int(y_ratio * nail[0]), int(x_ratio * nail[1])) for nail in nails]


def pull_order_to_array_bw(order, canvas, nails, strength):
    for pull_start, pull_end in zip(order, order[1:]):
        rr, cc, val = line_aa(
            nails[pull_start][0],
            nails[pull_start][1],
            nails[pull_end][0],
            nails[pull_end][1],
        )
        canvas[rr, cc] += val * strength
    return np.clip(canvas, a_min=0, a_max=1)


def pull_order_to_array_rgb(orders, canvas, nails, colors, strength):
    color_order_iterators = [iter(zip(order, order[1:])) for order in orders]
    steps = len(orders[0]) - 1
    for _ in range(max(steps, 0)):
        for color_idx, iterator in enumerate(color_order_iterators):
            try:
                pull_start, pull_end = next(iterator)
            except StopIteration:
                continue
            rr_aa, cc_aa, val_aa = line_aa(
                nails[pull_start][0],
                nails[pull_start][1],
                nails[pull_end][0],
                nails[pull_end][1],
            )
            val_aa_colored = np.repeat(val_aa[:, np.newaxis], len(colors), axis=1)
            canvas[rr_aa, cc_aa] += colors[color_idx] * val_aa_colored * strength
    return np.clip(canvas, a_min=0, a_max=1)


def _ensure_float_image(image: np.ndarray) -> np.ndarray:
    img = image.astype(np.float32)
    if np.any(img > 1.0):
        img = img / 255.0
    return img


def _prepare_source_image(image: np.ndarray, options: StringArtOptions) -> np.ndarray:
    img = _ensure_float_image(image)
    if options.radius1_multiplier == 1 and options.radius2_multiplier == 1:
        img = largest_square(img)
        img = resize(img, (options.side_len, options.side_len), preserve_range=True)
    return img


def generate_string_art_from_array(image: np.ndarray, options: StringArtOptions) -> StringArtResult:
    rng = np.random.default_rng()
    img = _prepare_source_image(image, options)
    shape = (len(img), len(img[0]))

    if options.rect:
        nails = create_rectangle_nail_positions(shape, options.nail_step)
    else:
        nails = create_circle_nail_positions(
            shape,
            options.nail_step,
            options.radius1_multiplier,
            options.radius2_multiplier,
        )

    print(f"Nails amount: {len(nails)}")

    nails_list = [(int(n[0]), int(n[1])) for n in nails]

    if options.rgb:
        iteration_strength = 0.1 if options.wb else -0.1
        r = img[:, :, 0]
        g = img[:, :, 1]
        b = img[:, :, 2]

        str_pic_r = init_canvas(shape, black=options.wb)
        pull_orders_r = create_art(
            nails,
            r,
            str_pic_r,
            iteration_strength,
            i_limit=options.pull_amount,
            random_nails=options.random_nails,
            rng=rng,
        )

        str_pic_g = init_canvas(shape, black=options.wb)
        pull_orders_g = create_art(
            nails,
            g,
            str_pic_g,
            iteration_strength,
            i_limit=options.pull_amount,
            random_nails=options.random_nails,
            rng=rng,
        )

        str_pic_b = init_canvas(shape, black=options.wb)
        pull_orders_b = create_art(
            nails,
            b,
            str_pic_b,
            iteration_strength,
            i_limit=options.pull_amount,
            random_nails=options.random_nails,
            rng=rng,
        )

        max_pulls = np.max([len(pull_orders_r), len(pull_orders_g), len(pull_orders_b)])
        pull_orders_r = pull_orders_r + [pull_orders_r[-1]] * (max_pulls - len(pull_orders_r))
        pull_orders_g = pull_orders_g + [pull_orders_g[-1]] * (max_pulls - len(pull_orders_g))
        pull_orders_b = pull_orders_b + [pull_orders_b[-1]] * (max_pulls - len(pull_orders_b))
        pull_orders = [
            [int(idx) for idx in pull_orders_r],
            [int(idx) for idx in pull_orders_g],
            [int(idx) for idx in pull_orders_b],
        ]

        color_image_dimens = (
            int(options.side_len * options.radius1_multiplier),
            int(options.side_len * options.radius2_multiplier),
            3,
        )
        blank = init_canvas(color_image_dimens, black=options.wb)
        scaled_nails = scale_nails(
            color_image_dimens[1] / shape[1],
            color_image_dimens[0] / shape[0],
            nails,
        )

        result_image = pull_order_to_array_rgb(
            pull_orders,
            blank,
            scaled_nails,
            (
                np.array((1.0, 0.0, 0.0)),
                np.array((0.0, 1.0, 0.0)),
                np.array((0.0, 0.0, 1.0)),
            ),
            options.export_strength if options.wb else -options.export_strength,
        )
    else:
        orig_pic = rgb2gray(img) * 0.9
        image_dimens = (
            int(options.side_len * options.radius1_multiplier),
            int(options.side_len * options.radius2_multiplier),
        )
        if options.wb:
            str_pic = init_canvas(shape, black=True)
            pull_order = create_art(
                nails,
                orig_pic,
                str_pic,
                0.05,
                i_limit=options.pull_amount,
                random_nails=options.random_nails,
                rng=rng,
            )
            blank = init_canvas(image_dimens, black=True)
        else:
            str_pic = init_canvas(shape, black=False)
            pull_order = create_art(
                nails,
                orig_pic,
                str_pic,
                -0.05,
                i_limit=options.pull_amount,
                random_nails=options.random_nails,
                rng=rng,
            )
            blank = init_canvas(image_dimens, black=False)

        scaled_nails = scale_nails(
            image_dimens[1] / shape[1],
            image_dimens[0] / shape[0],
            nails,
        )

        result_image = pull_order_to_array_bw(
            pull_order,
            blank,
            scaled_nails,
            options.export_strength if options.wb else -options.export_strength,
        )
        pull_orders = [[int(idx) for idx in pull_order]]
        print("Thread pull order by nail index:\n" + "-".join([str(idx) for idx in pull_order]))

    scaled_nails_list = [(int(n[0]), int(n[1])) for n in scaled_nails]
    mode = "rgb" if options.rgb else "bw"
    return StringArtResult(
        image=result_image,
        mode=mode,
        pull_orders=pull_orders,
        nails=nails_list,
        scaled_nails=scaled_nails_list,
        options=options,
    )


def _load_image_from_path(path: str) -> np.ndarray:
    img = mpimg.imread(path)
    return _ensure_float_image(img)


def _save_result_image(path: str, image: np.ndarray) -> None:
    mpimg.imsave(path, image, cmap=plt.get_cmap("gray"), vmin=0.0, vmax=1.0)


def _parse_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create String Art")
    parser.add_argument("-i", action="store", dest="input_file", required=True)
    parser.add_argument("-o", action="store", dest="output_file", required=True)
    parser.add_argument("-d", action="store", type=int, dest="side_len", default=300)
    parser.add_argument("-s", action="store", type=float, dest="export_strength", default=0.1)
    parser.add_argument("-l", action="store", type=int, dest="pull_amount", default=None)
    parser.add_argument("-r", action="store", type=int, dest="random_nails", default=None)
    parser.add_argument("-r1", action="store", type=float, dest="radius1_multiplier", default=1.0)
    parser.add_argument("-r2", action="store", type=float, dest="radius2_multiplier", default=1.0)
    parser.add_argument("-n", action="store", type=int, dest="nail_step", default=4)
    parser.add_argument("--wb", action="store_true")
    parser.add_argument("--rgb", action="store_true")
    parser.add_argument("--rect", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_cli_args()
    source_image = _load_image_from_path(args.input_file)
    options = StringArtOptions(
        side_len=args.side_len,
        export_strength=args.export_strength,
        pull_amount=args.pull_amount,
        random_nails=args.random_nails,
        radius1_multiplier=args.radius1_multiplier,
        radius2_multiplier=args.radius2_multiplier,
        nail_step=args.nail_step,
        wb=args.wb,
        rgb=args.rgb,
        rect=args.rect,
    )
    result = generate_string_art_from_array(source_image, options)
    _save_result_image(args.output_file, result.image)
