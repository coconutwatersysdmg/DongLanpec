import numpy as np
import matplotlib.pyplot as plt

# ============================================================
# 1. 中文字体设置
# ============================================================
plt.rcParams["font.sans-serif"] = [
    "Microsoft YaHei",
    "SimHei",
    "Arial Unicode MS"
]
plt.rcParams["axes.unicode_minus"] = False

# ============================================================
# 2. 数据
# ============================================================

# IF 验证集分位阈值
if_quantiles = np.array([
    0.9900,
    0.9925,
    0.9950,
    0.9975
])

# 不同 AE 分位阈值下的 F1
f1_ae_095 = np.array([
    0.9543,
    0.9572,
    0.9601,
    0.9485
])

f1_ae_097 = np.array([
    0.9585,
    0.9615,
    0.9645,
    0.9528
])

f1_ae_098 = np.array([
    0.9568,
    0.9598,
    0.9627,
    0.9494
])

f1_ae_099 = np.array([
    0.9568,
    0.9598,
    0.9627,
    0.9494
])

# ============================================================
# 3. 绘图
# ============================================================
fig, ax = plt.subplots(figsize=(7.2, 4.0))

ax.set_xlabel("IF Validation Quantile Threshold")
ax.set_ylabel("Binary F1")

ax.plot(
    if_quantiles,
    f1_ae_095,
    marker="o",
    label="AE Quantile 0.95"
)

ax.plot(
    if_quantiles,
    f1_ae_097,
    marker="s",
    label="AE Quantile 0.97"
)

ax.plot(
    if_quantiles,
    f1_ae_098,
    marker="^",
    label="AE Quantile 0.98"
)

ax.plot(
    if_quantiles,
    f1_ae_099,
    marker="x",
    label="AE Quantile 0.99"
)

ax.set_xticks(if_quantiles)

ax.set_xticklabels([
    "0.9900",
    "0.9925",
    "0.9950",
    "0.9975"
])

# 与原图接近的局部纵轴范围
ax.set_ylim(0.943, 0.973)

# ============================================================
# 5. 图例和样式
# ============================================================
ax.legend(
    loc="upper left",
    frameon=False,
    ncol=2
)

# 去掉顶部和右侧边框
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)

ax.tick_params(
    axis="both",
    labelsize=10
)

plt.tight_layout()

# ============================================================
# 6. 保存
# ============================================================


plt.show()