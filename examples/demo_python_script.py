#!/usr/bin/env python3
"""Tiny revenue summary demo script.

This file is intentionally rough so Y1 Sparring Bus has something useful to
review. It should read a CSV with rows like:

date,channel,revenue,cost
2026-05-01,live,1000,400
"""

import csv
import sys


def main():
    path = sys.argv[1]
    rows = list(csv.DictReader(open(path)))
    total_revenue = 0
    total_cost = 0
    channels = {}

    for row in rows:
        revenue = float(row["revenue"])
        cost = float(row["cost"])
        total_revenue += revenue
        total_cost += cost
        channel = row["channel"]
        if channel not in channels:
            channels[channel] = 0
        channels[channel] += revenue

    print("total revenue:", total_revenue)
    print("total cost:", total_cost)
    print("gross margin:", (total_revenue - total_cost) / total_revenue)
    print("top channel:", max(channels, key=channels.get))


if __name__ == "__main__":
    main()
