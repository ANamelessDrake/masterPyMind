# masterPyMind

**Author:** Justin Bard  
**Created:** 2026-07-02

A terminal [Mastermind](https://en.wikipedia.org/wiki/Mastermind_(board_game))
game in pure Python. One program, two audiences:

- **Humans** type color letters and read a colored board.
- **Scripts** pipe the same letters in and read terse, parseable output.

Colors are rendered with the [`jblib`](https://pypi.org/project/jblib/)
`jbcolor` API.

## Requirements

- Python 3.9+ (tested on 3.13)
- `jblib` (`pip install jblib`)

## Playing (human)

```bash
python3 masterpymind.py
```

You guess a code of color letters (default 6 colors: `R G B Y P O`). After each
guess you get feedback pegs:

- `●` right color **and** right position
- `○` right color, wrong position
- `·` not in the code

Crack the code before you run out of guesses.

## Options

| Flag | Default | Meaning |
|------|---------|---------|
| `--length N` | 4 | pegs in the secret code |
| `--guesses N` | 10 | guesses allowed |
| `--colors N` | 6 | palette size, 2–8 (`R G B Y P O T W`) |
| `--no-duplicates` | off | secret never repeats a color |
| `--seed N` | random | reproducible secret (handy for tests/bots) |
| `--machine` | auto | force machine output (see below) |

```bash
python3 masterpymind.py --length 5 --colors 8 --guesses 12
python3 masterpymind.py --no-duplicates --seed 42
```

## Driving it from a script

The input format is identical for humans and scripts: one guess per line,
color letters (case-insensitive, spaces ignored), e.g. `RGBY`.

Output switches to a terse, line-oriented protocol automatically whenever stdin
is not a terminal (a pipe or redirect), or when you pass `--machine`:

```
GAME length=<n> guesses=<n> colors=<LETTERS> duplicates=<0|1>
FEEDBACK <black> <white> <turn> <guess>
ERROR <message>            # invalid guess; does NOT consume a turn
WIN <turns>
LOSE <secret>
```

`black` = exact-position matches, `white` = right-color/wrong-position.

Example — a scripted playthrough with a fixed secret:

```bash
$ printf 'RGBY\nORRO\n' | python3 masterpymind.py --seed 42 --machine
GAME length=4 guesses=10 colors=RGBYPO duplicates=1
FEEDBACK 0 1 1 RGBY
FEEDBACK 4 0 2 ORRO
WIN 2
```

Exit code is `0` on a win, `1` on a loss.

## Solver bot

`solver.py` is a bot that plays the game entirely through the machine protocol
above — it launches `masterpymind.py --machine` as a subprocess and only reads
its stdout, never touching the secret. It's both a demo of the scripting
interface and a regression test of the scoring logic.

It uses **consistency filtering**: it starts with every possible code as a
hypothesis and, after each `FEEDBACK` line, discards any candidate that
wouldn't have produced that same score, then guesses a survivor.

```bash
python3 solver.py --seed 42          # solve one game, narrated
python3 solver.py --length 5 --colors 8
python3 solver.py --trials 300       # play 300 seeds, report a guess histogram
```

`--trials N` plays seeds `0..N-1` and prints a win rate and guess distribution;
it exits non-zero if any game is lost, so it works as a CI check.

