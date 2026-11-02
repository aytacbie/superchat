"""Visual search test: runs labelled photos through app.visual and reports how often it is
right, asks, or is confidently wrong.

Usage: python eval_visual.py <folder with the photos>   (add -v to print every photo)

tests/visual_cases.csv lists each photo with the class it shows, or "none" for things the
catalogue does not sell. The photos are the product images of the visual-search project.
"""
import csv
import sys
from collections import Counter
from pathlib import Path

from app import visual


def outcome(ranked, expected):
    ours = [r for r in ranked if r[1]]
    best, second = ours[0], ours[1]
    top = ranked[0]
    if best[2] >= visual.CONFIDENT:
        return "confident_right" if best[0] == expected else "confident_wrong"
    if best[2] >= visual.POSSIBLE and not (top is not best and top[2] >= visual.CONFIDENT):
        asked = {best[0]} | ({second[0]} if second[2] >= visual.POSSIBLE / 2 else set())
        return "asked_right" if expected in asked else "asked_wrong"
    return "rejected"


def main(folder, verbose):
    cases = list(csv.reader(open(Path(__file__).parent / "tests" / "visual_cases.csv", encoding="utf-8")))[1:]
    pos, neg = Counter(), Counter()
    for name, expected in cases:
        ranked = visual.classify((Path(folder) / name).read_bytes())
        result = outcome(ranked, expected)
        (pos if expected != "none" else neg)[result] += 1
        if verbose or result in ("confident_wrong",) or (expected != "none" and result != "confident_right"):
            guess = ", ".join(f"{label} {p:.0%}" for label, _, p in ranked[:3])
            print(f"  {result:<16} {name:<55} expected {expected:<15} got {guess}")
    n_pos, n_neg = sum(pos.values()), sum(neg.values())
    print(f"\nCatalogue products ({n_pos} photos):")
    print(f"  identified with confidence  {pos['confident_right']:>3}  ({pos['confident_right'] / n_pos:.0%})")
    print(f"  asked, right answer offered {pos['asked_right']:>3}  ({pos['asked_right'] / n_pos:.0%})")
    print(f"  asked, wrong options        {pos['asked_wrong']:>3}")
    print(f"  confidently wrong           {pos['confident_wrong']:>3}")
    print(f"  said 'not in catalogue'     {pos['rejected']:>3}")
    print(f"Things we do not sell ({n_neg} photos):")
    print(f"  said 'not in catalogue'     {neg['rejected']:>3}  ({neg['rejected'] / n_neg:.0%})")
    print(f"  asked the user              {neg['asked_right'] + neg['asked_wrong']:>3}")
    print(f"  confidently wrong product   {neg['confident_wrong']:>3}  ({neg['confident_wrong'] / n_neg:.0%})")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "-v"]
    main(args[0] if args else "../visual-search/data/images", "-v" in sys.argv)
