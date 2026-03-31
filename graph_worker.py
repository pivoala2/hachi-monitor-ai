import re
from collections import defaultdict
from datetime import datetime, timedelta
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def parse_summary_lines(lines):
    events = []
    for l in lines:
        l = l.strip()
        if not l or l.startswith("#"):
            continue
        m = re.match(
            r'\[(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})\]\s*判定:\s*\[(.+?)\]\s*猫体重:\s*([\d.]+)g\s*排泄量:\s*([-\d.]+)g',
            l
        )
        if not m:
            continue
        label = m.group(2)
        cat_w = float(m.group(3))
        # Skip N/A or zero weight
        if label == "N/A" or cat_w == 0.0:
            continue
        events.append({
            "dt": datetime.strptime(m.group(1), "%Y/%m/%d %H:%M:%S"),
            "label": label,
            "cat_w": cat_w,
            "waste_w": float(m.group(4)),
        })
    return events


def predict_next_poop(poop_times):
    """Returns (predicted datetime, median interval hours) or (None, None)"""
    if len(poop_times) < 3:
        return None, None
    intervals = []
    for i in range(1, len(poop_times)):
        diff = (poop_times[i] - poop_times[i - 1]).total_seconds() / 3600
        if 6 <= diff <= 96:
            intervals.append(diff)
    if not intervals:
        return None, None
    intervals.sort()
    median_interval = intervals[len(intervals) // 2]
    predicted = poop_times[-1] + timedelta(hours=median_interval)
    return predicted, median_interval


def generate_last_month_weight_graph_from_log(lines):
    import matplotlib.gridspec as gridspec

    OUTPUT_PATH = "/app/shared_summary/last_month_weight.png"

    events = parse_summary_lines(lines)
    if not events:
        print("No valid data found.")
        return None

    now = datetime.now()
    cutoff = now - timedelta(days=30)
    events = [e for e in events if e["dt"] >= cutoff]
    if not events:
        print("No data in last 30 days.")
        return None

    # Daily aggregation
    daily_weights = defaultdict(list)
    daily_pee = defaultdict(int)
    daily_poop = defaultdict(int)

    for e in events:
        d = e["dt"].date()
        daily_weights[d].append(e["cat_w"] / 1000)
        if "poop" in e["label"]:
            daily_poop[d] += 1
        elif "pee" in e["label"]:
            daily_pee[d] += 1

    all_days = sorted(set(daily_weights.keys()))
    weights_avg = [sum(daily_weights[d]) / len(daily_weights[d]) for d in all_days]
    pee_counts = [daily_pee[d] for d in all_days]
    poop_counts = [daily_poop[d] for d in all_days]

    # Week-over-week comparison
    week1_days = [d for d in all_days if now.date() - timedelta(days=7) <= d <= now.date()]
    week2_days = [d for d in all_days if now.date() - timedelta(days=14) <= d < now.date() - timedelta(days=7)]

    def day_avg(d):
        return sum(daily_weights[d]) / len(daily_weights[d])

    week1_avg = sum(day_avg(d) for d in week1_days) / len(week1_days) if week1_days else None
    week2_avg = sum(day_avg(d) for d in week2_days) / len(week2_days) if week2_days else None

    # Poop interval & prediction
    poop_events = [e for e in events if "poop" in e["label"]]
    poop_times = [e["dt"] for e in poop_events]
    predicted_poop, median_interval = predict_next_poop(poop_times)

    poop_intervals = []
    for i in range(1, len(poop_times)):
        diff = (poop_times[i] - poop_times[i - 1]).total_seconds() / 3600
        if 6 <= diff <= 96:
            poop_intervals.append((poop_times[i].date(), diff))

    hours_since_poop = None
    if poop_times:
        hours_since_poop = (now - poop_times[-1]).total_seconds() / 3600

    # Alert detection
    overall_avg = sum(weights_avg) / len(weights_avg)
    alert_days = {d for d, w in zip(all_days, weights_avg) if abs(w - overall_avg) >= 0.2}
    poop_alert = hours_since_poop is not None and hours_since_poop >= 48

    # Plot
    fig = plt.figure(figsize=(15, 10))
    fig.patch.set_facecolor("#f5f5f5")
    gs = gridspec.GridSpec(2, 1, height_ratios=[3, 1.5], hspace=0.35)

    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1])

    labels_str = [d.strftime("%m/%d") for d in all_days]
    x = list(range(len(all_days)))

    # ========== Top: Weight ==========
    ax1.set_facecolor("#fafafa")
    ax1.plot(x, weights_avg, linewidth=1.5, alpha=0.4, color="#aaaaaa")

    last7_start = max(0, len(weights_avg) - 7)
    ax1.plot(x[last7_start:], weights_avg[last7_start:],
             linewidth=3.5, color="#1f77b4", alpha=0.9, label="Last 7 days")

    ax1.axhline(overall_avg, linestyle="--", linewidth=1.2,
                alpha=0.6, color="#888888", label=f"30d avg: {overall_avg:.2f}kg")

    for i in range(len(weights_avg)):
        d = all_days[i]
        w = weights_avg[i]
        if d in alert_days:
            color = "#ff7f0e"
        elif i == 0:
            color = "#666666"
        elif w > weights_avg[i - 1]:
            color = "#2ca02c"
        elif w < weights_avg[i - 1]:
            color = "#d62728"
        else:
            color = "#7f7f7f"

        is_recent = i >= last7_start
        ax1.scatter(x[i], w, color=color, s=180, edgecolors='k', zorder=4)
        ax1.text(x[i], w + 0.015, f"{w:.2f}",
                 ha="center", va="bottom", fontsize=9,
                 color=color, weight="bold" if is_recent else "normal")

    if week1_avg and week2_avg:
        diff = week1_avg - week2_avg
        sign = "+" if diff >= 0 else ""
        color = "#2ca02c" if diff >= 0 else "#d62728"
        ax1.text(0.01, 0.97,
                 f"Last 7d avg: {week1_avg:.2f}kg  vs prev week: {sign}{diff*1000:.0f}g",
                 transform=ax1.transAxes, fontsize=11, va="top",
                 color=color, weight="bold",
                 bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.7))

    ax1.set_xticks(x)
    ax1.set_xticklabels(labels_str, rotation=45, fontsize=9)
    ax1.set_ylabel("Weight (kg)", fontsize=11)
    ax1.set_title("Hachi - Weight Trend (Last 30 days)", fontsize=14, weight="bold", pad=12)
    ax1.legend(loc="upper right", fontsize=9)
    ax1.grid(True, linestyle="--", alpha=0.3)
    ax1.set_ylim(min(weights_avg) - 0.15, max(weights_avg) + 0.18)

    # ========== Bottom: Excretion ==========
    ax2.set_facecolor("#fafafa")

    bar_width = 0.35
    ax2.bar([i - bar_width / 2 for i in x], pee_counts,
            width=bar_width, label="Pee", color="#4da6ff", alpha=0.8)
    ax2.bar([i + bar_width / 2 for i in x], poop_counts,
            width=bar_width, label="Poop", color="#a0522d", alpha=0.8)

    if poop_intervals:
        ax2r = ax2.twinx()
        interval_x = [all_days.index(d) for d, h in poop_intervals if d in all_days]
        interval_y = [h for d, h in poop_intervals if d in all_days]
        ax2r.plot(interval_x, interval_y, color="#ff7f0e", linewidth=1.5,
                  marker="D", markersize=5, alpha=0.8, label="Poop interval (h)")
        ax2r.set_ylabel("Poop interval (h)", fontsize=9, color="#ff7f0e")
        ax2r.tick_params(axis='y', labelcolor="#ff7f0e")
        ax2r.legend(loc="upper right", fontsize=8)

    ax2.set_xticks(x)
    ax2.set_xticklabels(labels_str, rotation=45, fontsize=9)
    ax2.set_ylabel("Count", fontsize=10)
    ax2.set_title("Excretion count / Poop interval", fontsize=11, weight="bold")
    ax2.legend(loc="upper left", fontsize=9)
    ax2.grid(True, linestyle="--", alpha=0.3)
    ax2.yaxis.set_major_locator(plt.MaxNLocator(integer=True))

    # ========== Info bar ==========
    info_lines = []

    if predicted_poop and median_interval:
        remaining = (predicted_poop - now).total_seconds() / 3600
        if remaining > 0:
            info_lines.append(
                f"Next poop: {predicted_poop.strftime('%m/%d %H:%M')}  "
                f"(in {remaining:.1f}h)  median interval: {median_interval:.1f}h"
            )
        else:
            info_lines.append(
                f"Poop overdue since {predicted_poop.strftime('%m/%d %H:%M')}  "
                f"({-remaining:.1f}h ago)  median interval: {median_interval:.1f}h"
            )

    if poop_alert:
        info_lines.append(f"WARNING: No poop for {hours_since_poop:.1f}h -> check needed!")
    elif hours_since_poop is not None:
        info_lines.append(
            f"Last poop: {poop_times[-1].strftime('%m/%d %H:%M')}  ({hours_since_poop:.1f}h ago)"
        )

    if info_lines:
        fig.text(0.5, 0.01, "   |   ".join(info_lines),
                 ha="center", va="bottom", fontsize=10,
                 bbox=dict(boxstyle="round,pad=0.4", facecolor="#fffbe6",
                           edgecolor="#f0c040", alpha=0.95))

    plt.savefig(OUTPUT_PATH, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Graph saved: {OUTPUT_PATH}")
    return OUTPUT_PATH


# -----------------------------
# Entry Point
# -----------------------------
if __name__ == "__main__":
    log_path = "/app/shared_summary/summary.txt"
    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    result = generate_last_month_weight_graph_from_log(lines)
    print("Done:", result)
