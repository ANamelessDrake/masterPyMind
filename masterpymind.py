#!/usr/bin/env python3
"""masterPyMind -- a terminal Mastermind game.

Playable two ways, through the exact same stdin interface:

  * A human types color letters (e.g. ``RGBY``) and reads a colored board.
  * A script pipes the same letters in and reads terse, parseable output.

The only thing that changes between the two is *rendering*. When stdout is a
real terminal you get colored pegs; when stdin is piped (or ``--machine`` is
passed) you get machine-readable ``FEEDBACK <black> <white>`` lines instead.

Colors come from the ``jblib`` module's modern color API (``jbcolor``).

Usage examples::

    python3 masterpymind.py                     # classic, interactive
    python3 masterpymind.py --length 5 --colors 8 --guesses 12
    echo -e "RGBY\\nRRGG" | python3 masterpymind.py --seed 42 --machine
"""

import argparse
import sys
from collections import Counter

from jblib import jbcolor


# --- Color palette ----------------------------------------------------------
# Each peg is identified by a single uppercase letter. That letter is what a
# human types and what a script pipes in -- so the game's "alphabet" is just
# the first N entries of this ordered table. ``fg`` is chosen per background so
# the letter stays readable on its colored swatch.
#
#   (letter, jblib color name, contrast foreground)
PALETTE = [
    ("R", "red", "bright_white"),
    ("G", "green", "black"),
    ("B", "blue", "bright_white"),
    ("Y", "yellow", "black"),
    ("P", "purple", "bright_white"),
    ("O", "orange", "black"),
    ("T", "teal", "black"),
    ("W", "white", "black"),
]
MAX_COLORS = len(PALETTE)


class Config:
    """Resolved game settings for a single session."""

    def __init__(self, length, guesses, num_colors, duplicates, seed, machine):
        self.length = length
        self.guesses = guesses
        self.num_colors = num_colors
        self.duplicates = duplicates
        self.seed = seed
        self.machine = machine
        # The active alphabet: first ``num_colors`` letters of the palette.
        self.letters = [p[0] for p in PALETTE[:num_colors]]
        self.color_of = {p[0]: (p[1], p[2]) for p in PALETTE[:num_colors]}


# --- Core game logic --------------------------------------------------------
def make_secret(cfg, rng):
    """Generate the hidden code as a list of color letters."""
    if cfg.duplicates:
        return [rng.choice(cfg.letters) for _ in range(cfg.length)]
    # Sampling without replacement guarantees no repeated colors.
    return rng.sample(cfg.letters, cfg.length)


def score_guess(secret, guess):
    """Return (black, white) peg counts for a guess.

    Black pegs: right color in the right position.
    White pegs: right color in the wrong position.

    Duplicates are handled correctly by counting, per color, how many pegs the
    guess and secret have in common, then subtracting the exact matches. This
    is the classic Mastermind scoring and avoids double-counting repeats.
    """
    black = sum(s == g for s, g in zip(secret, guess))
    secret_counts = Counter(secret)
    guess_counts = Counter(guess)
    common = sum(min(secret_counts[c], guess_counts[c]) for c in guess_counts)
    white = common - black
    return black, white


def parse_guess(raw, cfg):
    """Validate raw input into a list of letters, or raise ValueError."""
    guess = raw.strip().upper().replace(" ", "")
    if len(guess) != cfg.length:
        raise ValueError(
            f"expected {cfg.length} letters, got {len(guess)}"
        )
    bad = [ch for ch in guess if ch not in cfg.color_of]
    if bad:
        raise ValueError(f"invalid color(s): {''.join(bad)}")
    return list(guess)


# --- Rendering: human vs. machine ------------------------------------------
def peg(letter, cfg):
    """A colored swatch for one peg, e.g. a bold ' R ' on a red background."""
    name, fg = cfg.color_of[letter]
    return jbcolor(f" {letter} ", fg=fg, bg=name, bold=True)


def render_feedback_human(black, white, cfg):
    """Filled red pegs for exact hits, hollow white for color-only, dim dots."""
    none = cfg.length - black - white
    pegs = (
        [jbcolor("●", fg="bright_red", bold=True)] * black
        + [jbcolor("○", fg="bright_white", bold=True)] * white
        + [jbcolor("·", fg="bright_black")] * none
    )
    return " ".join(pegs)


class HumanUI:
    """Colored, interactive presentation for a person at the keyboard."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.history = []  # list of (guess_letters, black, white)

    def intro(self):
        cfg = self.cfg
        swatches = " ".join(peg(l, cfg) for l in cfg.letters)
        print()
        print(jbcolor("  masterPyMind", fg="bright_teal", bold=True))
        print(jbcolor("  " + "─" * 40, fg="bright_black"))
        print(f"  Crack the {cfg.length}-peg code in {cfg.guesses} guesses.")
        print(f"  Colors: {swatches}")
        dup = "may repeat" if cfg.duplicates else "no repeats"
        print(jbcolor(f"  ({dup}). Type letters like "
                      f"{''.join(cfg.letters[:cfg.length])} and press Enter.",
                      fg="bright_black"))
        print(jbcolor("  Feedback:  ● exact position   "
                      "○ right color, wrong spot   · no match",
                      fg="bright_black"))
        print()

    def board(self):
        cfg = self.cfg
        for i, (guess, black, white) in enumerate(self.history, 1):
            row = " ".join(peg(l, cfg) for l in guess)
            fb = render_feedback_human(black, white, cfg)
            print(f"  {i:>2} │ {row}   {fb}")

    def prompt(self, turn):
        remaining = self.cfg.guesses - turn + 1
        return input(jbcolor(f"  guess {turn}/{self.cfg.guesses} "
                             f"({remaining} left) > ", fg="bright_teal"))

    def record(self, guess, black, white):
        self.history.append((guess, black, white))
        row = " ".join(peg(l, self.cfg) for l in guess)
        fb = render_feedback_human(black, white, self.cfg)
        print(f"       {row}   {fb}")

    def error(self, msg):
        print(jbcolor(f"  ! {msg}", fg="bright_red"))

    def win(self, turns):
        print()
        print(jbcolor(f"  ✔ Cracked it in {turns} "
                      f"guess{'es' if turns != 1 else ''}!",
                      fg="bright_green", bold=True))

    def lose(self, secret):
        row = " ".join(peg(l, self.cfg) for l in secret)
        print()
        print(jbcolor("  ✗ Out of guesses. The code was:",
                      fg="bright_red", bold=True))
        print(f"     {row}")


class MachineUI:
    """Terse, line-oriented presentation for a controlling script.

    Protocol (one record per line, space-delimited, easy to grep/split):

        GAME length=<n> guesses=<n> colors=<LETTERS> duplicates=<0|1>
        FEEDBACK <black> <white> <turn> <guess>
        ERROR <message>
        WIN <turns>
        LOSE <secret>
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self.turn = 0

    def intro(self):
        cfg = self.cfg
        print(f"GAME length={cfg.length} guesses={cfg.guesses} "
              f"colors={''.join(cfg.letters)} "
              f"duplicates={1 if cfg.duplicates else 0}", flush=True)

    def board(self):
        pass  # A script keeps its own state; no board redraw needed.

    def prompt(self, turn):
        return input()

    def record(self, guess, black, white):
        self.turn += 1
        print(f"FEEDBACK {black} {white} {self.turn} {''.join(guess)}",
              flush=True)

    def error(self, msg):
        print(f"ERROR {msg}", flush=True)

    def win(self, turns):
        print(f"WIN {turns}", flush=True)

    def lose(self, secret):
        print(f"LOSE {''.join(secret)}", flush=True)


# --- Game driver ------------------------------------------------------------
def play(cfg, rng):
    ui = MachineUI(cfg) if cfg.machine else HumanUI(cfg)
    secret = make_secret(cfg, rng)
    ui.intro()

    turn = 1
    while turn <= cfg.guesses:
        try:
            raw = ui.prompt(turn)
        except EOFError:
            # Script closed the pipe (or human hit Ctrl-D) before winning.
            break
        except KeyboardInterrupt:
            print()
            break

        try:
            guess = parse_guess(raw, cfg)
        except ValueError as exc:
            ui.error(str(exc))
            continue  # Bad input doesn't consume a guess.

        black, white = score_guess(secret, guess)
        ui.record(guess, black, white)

        if black == cfg.length:
            ui.win(turn)
            return 0
        turn += 1

    ui.lose(secret)
    return 1


def build_parser():
    p = argparse.ArgumentParser(
        prog="masterpymind",
        description="A terminal Mastermind game for humans or scripts.",
    )
    p.add_argument("--length", type=int, default=4,
                   help="number of pegs in the secret code (default 4)")
    p.add_argument("--guesses", type=int, default=10,
                   help="number of guesses allowed (default 10)")
    p.add_argument("--colors", type=int, default=6, metavar="N",
                   help=f"how many colors to use, 2-{MAX_COLORS} (default 6)")
    p.add_argument("--no-duplicates", dest="duplicates", action="store_false",
                   help="secret code will not repeat any color")
    p.add_argument("--seed", type=int, default=None,
                   help="RNG seed for a reproducible secret (useful in tests)")
    p.add_argument("--machine", action="store_true",
                   help="force terse machine-readable output "
                        "(auto-enabled when stdin is not a terminal)")
    return p


def resolve_config(args):
    """Validate CLI args and fold in stdin auto-detection. Returns Config."""
    if not (2 <= args.colors <= MAX_COLORS):
        raise SystemExit(f"--colors must be between 2 and {MAX_COLORS}")
    if args.length < 1:
        raise SystemExit("--length must be at least 1")
    if args.guesses < 1:
        raise SystemExit("--guesses must be at least 1")
    if not args.duplicates and args.length > args.colors:
        raise SystemExit(
            f"--no-duplicates needs --length ({args.length}) "
            f"<= --colors ({args.colors})")

    # A piped/redirected stdin means a script is driving us -> machine output.
    machine = args.machine or not sys.stdin.isatty()

    return Config(
        length=args.length,
        guesses=args.guesses,
        num_colors=args.colors,
        duplicates=args.duplicates,
        seed=args.seed,
        machine=machine,
    )


def main(argv=None):
    import random

    args = build_parser().parse_args(argv)
    cfg = resolve_config(args)
    rng = random.Random(cfg.seed)
    return play(cfg, rng)


if __name__ == "__main__":
    sys.exit(main())
