#!/usr/bin/env python3
"""A bot that plays masterPyMind through its machine interface.

This never imports the game's state or peeks at the secret. It launches
``masterpymind.py --machine`` as a subprocess and talks to it purely over
stdin/stdout -- exactly as any external script (in any language) would. That's
the point: if a blind subprocess can win, the machine protocol is complete.

Strategy: **consistency filtering**. Start with every possible code as a
hypothesis. After each ``FEEDBACK <black> <white>`` line, discard any candidate
that *wouldn't have produced that same score* against the guess we just made,
then guess a survivor. We reuse the game's own ``score_guess`` to test
hypotheses -- a neat symmetry, and it means a scoring bug would make the bot
lose (so this doubles as a test harness; see ``--trials``).

Usage::

    python3 solver.py --seed 42            # solve one game, narrated
    python3 solver.py --length 5 --colors 8
    python3 solver.py --trials 200         # play 200 seeds, report stats
"""

import argparse
import itertools
import subprocess
import sys

from jblib import jbcolor

from masterpymind import score_guess, PALETTE, MAX_COLORS

# Above this many hypotheses, full enumeration gets slow/memory-heavy. The
# classic 6-color/4-peg game is only 1296, so this ceiling is generous.
MAX_CANDIDATES = 500_000


def build_candidates(letters, length, duplicates):
    """Every code the secret could be, as a list of tuples."""
    if duplicates:
        space = len(letters) ** length
        gen = itertools.product(letters, repeat=length)
    else:
        # falling factorial: len(letters) * (len-1) * ...
        space = 1
        for k in range(length):
            space *= len(letters) - k
        gen = itertools.permutations(letters, length)
    if space > MAX_CANDIDATES:
        raise SystemExit(
            f"search space is {space:,} codes (> {MAX_CANDIDATES:,}); "
            "too large for this solver -- try fewer colors or a shorter code")
    return list(gen)


def parse_game_line(line):
    """Turn 'GAME length=4 guesses=10 colors=RGBYPO duplicates=1' into a dict."""
    fields = {}
    for token in line.split()[1:]:
        key, _, value = token.partition("=")
        fields[key] = value
    return {
        "length": int(fields["length"]),
        "guesses": int(fields["guesses"]),
        "letters": list(fields["colors"]),
        "duplicates": fields["duplicates"] == "1",
    }


def choose(candidates):
    """Pick the next guess. First survivor is simple and solves reliably."""
    return candidates[0]


def solve_one(game_args, verbose=False):
    """Drive one game to completion. Returns (won, turns, secret_or_None)."""
    proc = subprocess.Popen(
        [sys.executable, "masterpymind.py", "--machine", *game_args],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )

    def say(msg):
        if verbose:
            print(msg)

    def send(guess):
        proc.stdin.write("".join(guess) + "\n")
        proc.stdin.flush()

    rules = parse_game_line(proc.stdout.readline())
    candidates = build_candidates(
        rules["letters"], rules["length"], rules["duplicates"])
    say(jbcolor(f"  {len(candidates):,} possible codes to start.",
                fg="bright_black"))

    guess = choose(candidates)
    send(guess)

    won, turns, secret = False, None, None
    for line in proc.stdout:
        parts = line.split()
        kind = parts[0]

        if kind == "FEEDBACK":
            black, white, turn = int(parts[1]), int(parts[2]), int(parts[3])
            before = len(candidates)
            # Keep only hypotheses that would score identically to what we saw.
            candidates = [c for c in candidates
                          if score_guess(c, guess) == (black, white)]
            say(f"  {turn:>2}: guessed {jbcolor(''.join(guess), fg='bright_teal')}"
                f"  ->  {black}● {white}○   "
                + jbcolor(f"({before} -> {len(candidates)} left)",
                          fg="bright_black"))
            if black == rules["length"]:
                continue  # solved; a WIN line follows.
            if not candidates:
                say(jbcolor("  no candidates left -- scoring inconsistency!",
                            fg="bright_red"))
                break
            guess = choose(candidates)
            send(guess)

        elif kind == "WIN":
            won, turns = True, int(parts[1])
            say(jbcolor(f"  solved in {turns} guesses.",
                        fg="bright_green", bold=True))
            break

        elif kind == "LOSE":
            secret = parts[1]
            say(jbcolor(f"  lost -- secret was {secret}.", fg="bright_red"))
            break

        elif kind == "ERROR":
            say(jbcolor(f"  game rejected a guess: {line.strip()}",
                        fg="bright_red"))
            break

    proc.stdin.close()
    proc.wait()
    return won, turns, secret


def game_args_from(args):
    """Translate solver CLI flags into masterpymind.py flags."""
    out = ["--length", str(args.length),
           "--colors", str(args.colors),
           "--guesses", str(args.guesses)]
    if not args.duplicates:
        out.append("--no-duplicates")
    return out


def run_trials(args):
    """Play many seeded games and report a win-rate + guess distribution."""
    base = game_args_from(args)
    wins, turn_counts = 0, []
    for seed in range(args.trials):
        won, turns, secret = solve_one(base + ["--seed", str(seed)])
        if won:
            wins += 1
            turn_counts.append(turns)
        else:
            print(jbcolor(f"  seed {seed}: LOST (secret {secret})",
                          fg="bright_red"))

    print()
    print(jbcolor(f"  {wins}/{args.trials} solved", fg="bright_green", bold=True)
          + jbcolor(f"  ({100 * wins // args.trials}% win rate)",
                    fg="bright_black"))
    if turn_counts:
        dist = {}
        for t in turn_counts:
            dist[t] = dist.get(t, 0) + 1
        avg = sum(turn_counts) / len(turn_counts)
        print(f"  guesses: avg {avg:.2f}, best {min(turn_counts)}, "
              f"worst {max(turn_counts)}")
        for t in sorted(dist):
            bar = "█" * dist[t]
            print(f"    {t:>2} guesses: {jbcolor(bar, fg='bright_teal')} "
                  f"{dist[t]}")
    # Exit non-zero if any game was lost -- makes this usable in CI.
    return 0 if wins == args.trials else 1


def build_parser():
    p = argparse.ArgumentParser(
        prog="solver",
        description="A bot that plays masterPyMind over its machine protocol.")
    p.add_argument("--length", type=int, default=4)
    p.add_argument("--guesses", type=int, default=10)
    p.add_argument("--colors", type=int, default=6, metavar="N",
                   help=f"palette size, 2-{MAX_COLORS}")
    p.add_argument("--no-duplicates", dest="duplicates", action="store_false")
    p.add_argument("--seed", type=int, default=None,
                   help="seed for a single reproducible game")
    p.add_argument("--trials", type=int, default=None, metavar="N",
                   help="play N seeded games (0..N-1) and report stats")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.trials is not None:
        return run_trials(args)
    seed_args = ["--seed", str(args.seed)] if args.seed is not None else []
    won, turns, secret = solve_one(
        game_args_from(args) + seed_args, verbose=True)
    return 0 if won else 1


if __name__ == "__main__":
    sys.exit(main())
