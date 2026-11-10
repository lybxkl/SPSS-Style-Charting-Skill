"""Known-answer tests for ``methods_lib``.

Every number the library reports is recomputed here by a *second* route —
scipy, statsmodels, or the formula written out by hand — and compared. The
point is not line coverage but number coverage: a wrong standard error, a
cluster centre left in z-score units, or a Wilks Λ with mismatched degrees of
freedom passes every smoke test and still ruins a paper.

The library rounds for presentation (4 dp in most tables, 3 in some), so
comparisons go through ``assertRounded``: it rounds the hand value to the
precision the library actually kept instead of pretending full precision
survived.
"""
import math
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

SKILL = Path(__file__).resolve().parents[1] / "empirical-research-pipeline"
sys.path.insert(0, str(SKILL / "scripts"))

import methods_lib as ML  # noqa: E402
import methods_pack as MP  # noqa: E402

ALPHA = 0.05


def table(res, name):
    for tname, t in res.tables:
        if tname == name:
            return t
    raise AssertionError(
        f"{res.method}: 没有表 {name!r}，实际有 {[t[0] for t in res.tables]}")


def col(df, name):
    if name not in df.columns:
        raise AssertionError(f"表里没有列 {name!r}，实际列：{list(df.columns)}")
    return df[name]


class Base(unittest.TestCase):
    def assertRounded(self, got, want, nd=4, msg=""):
        """got 是库里的值（已按 nd 位四舍五入），want 是独立路径的原始值。"""
        self.assertAlmostEqual(float(got), round(float(want), nd), places=nd, msg=msg)


# --------------------------------------------------------------------------- #
# 1. describe
# --------------------------------------------------------------------------- #
class DescribeTest(Base):
    def setUp(self):
        rng = np.random.default_rng(7)
        self.normal = rng.normal(50, 10, 200)
        self.skewed = rng.lognormal(0, 1, 200)
        self.cat = pd.Series(rng.choice(["甲", "乙", "丙"], 200, p=[0.6, 0.3, 0.1]))
        self.df = pd.DataFrame({"norm": self.normal, "skew": self.skewed, "cat": self.cat,
                                "empty": [np.nan] * 200, "const": [3.5] * 200})
        self.tab = table(ML.describe(self.df, alpha=ALPHA), "descriptive").set_index("variable")

    def test_continuous_centre_matches_numpy(self):
        row = self.tab.loc["norm"]
        self.assertEqual(row["type"], "连续")
        self.assertRounded(row["mean"], np.mean(self.normal))
        self.assertRounded(row["sd"], np.std(self.normal, ddof=1))
        self.assertRounded(row["median"], np.median(self.normal))
        self.assertRounded(row["p25"], np.quantile(self.normal, 0.25))
        self.assertRounded(row["p75"], np.quantile(self.normal, 0.75))

    def test_skewed_variable_is_reported_as_median(self):
        row = self.tab.loc["skew"]
        p = stats.shapiro(self.skewed).pvalue
        if p < ALPHA:
            self.assertIn("中位数", row["report"])
        else:  # pragma: no cover
            self.assertIn("均值", row["report"])

    def test_all_missing_column_is_visible_not_dropped(self):
        self.assertIn("empty", self.tab.index)
        row = self.tab.loc["empty"]
        self.assertEqual(int(row["n"]), 0)
        self.assertEqual(row["type"], "缺失")
        self.assertIn("整列缺失", row["report"])

    def test_constant_column_is_labelled_constant(self):
        row = self.tab.loc["const"]
        self.assertEqual(row["type"], "常数")
        self.assertEqual(float(row["sd"]), 0.0)
        self.assertIn("恒为", row["report"])

    def test_categorical_mode_and_percent(self):
        row = self.tab.loc["cat"]
        vc = self.cat.value_counts()
        self.assertEqual(row["type"], "分类")
        self.assertEqual(int(row["levels"]), int(vc.size))
        self.assertEqual(str(row["mode"]), str(vc.index[0]))
        self.assertRounded(row["mode_pct"], vc.iloc[0] / vc.sum() * 100, nd=1)


# --------------------------------------------------------------------------- #
# 2. normality
# --------------------------------------------------------------------------- #
class NormalityTest(Base):
    def test_shapiro_p_matches_scipy(self):
        x = np.random.default_rng(1).normal(0, 1, 120)
        res = ML.normality(pd.DataFrame({"x": x}), "x")
        self.assertRounded(res.stats["p"], stats.shapiro(x).pvalue, nd=6)
        self.assertEqual(bool(res.stats["normal"]), stats.shapiro(x).pvalue >= ALPHA)

    def test_strongly_skewed_is_not_normal(self):
        x = np.random.default_rng(2).lognormal(0, 1.5, 200)
        self.assertFalse(bool(ML.normality(pd.DataFrame({"x": x}), "x").stats["normal"]))


# --------------------------------------------------------------------------- #
# 3. chi-square
# --------------------------------------------------------------------------- #
class ChiSquareTest(Base):
    def setUp(self):
        rng = np.random.default_rng(3)
        self.df = pd.DataFrame({"a": rng.choice(["甲", "乙"], 240),
                                "b": rng.choice(["低", "中", "高"], 240)})
        self.tab = pd.crosstab(self.df["a"], self.df["b"])
        self.res = ML.chi_square(self.df, "a", "b")

    def test_chi2_dof_and_p_match_scipy(self):
        chi2, p, dof, _ = stats.chi2_contingency(self.tab, correction=False)
        self.assertRounded(self.res.stats["chi2"], chi2)
        self.assertRounded(self.res.stats["p"], p, nd=6)
        self.assertEqual(int(self.res.stats["dof"]), int(dof))

    def test_cramers_v_formula(self):
        n = int(self.tab.values.sum())
        want = math.sqrt(self.res.stats["chi2"] / (n * (min(self.tab.shape) - 1)))
        self.assertRounded(self.res.stats["cramers_v"], want)

    def test_tables_keep_the_row_labels(self):
        # 三张表都要能看出第一行是哪一组；`pd.DataFrame(tab)` 会把 index 变成 0/1。
        for name in ("contingency", "expected", "row_percent"):
            t = table(self.res, name)
            self.assertEqual(int(len(t)), self.tab.shape[0])
            self.assertEqual([str(v) for v in t.iloc[:, 0]], list(self.tab.index),
                             f"{name} 丢了行标签")

    def test_contingency_and_row_percent_values(self):
        got = table(self.res, "contingency").set_index(table(self.res, "contingency").columns[0])
        self.assertTrue(np.array_equal(got.values, self.tab.values))
        rp = table(self.res, "row_percent").set_index(
            table(self.res, "row_percent").columns[0])
        want = (self.tab.div(self.tab.sum(axis=1), axis=0) * 100).round(1)
        self.assertTrue(np.allclose(rp.values, want.values, atol=0.05))
        self.assertTrue(np.allclose(rp.sum(axis=1).values, 100.0, atol=0.2))

    def test_small_expected_switches_to_fisher(self):
        df = pd.DataFrame({"a": ["p"] * 8 + ["q"] * 8,
                           "b": ["y"] * 7 + ["n"] + ["y"] + ["n"] * 7})
        res = ML.chi_square(df, "a", "b")
        self.assertIn("fisher_p", res.stats)
        self.assertIn("Fisher", " ".join(res.verdict))


# --------------------------------------------------------------------------- #
# 4. chi-square pairs
# --------------------------------------------------------------------------- #
class ChiSquarePairsTest(Base):
    def setUp(self):
        rng = np.random.default_rng(4)
        self.df = pd.DataFrame({"g": rng.choice(["A", "B", "C"], 300),
                                "y": rng.choice(["低", "中", "高"], 300)})
        self.res = ML.chi_square_pairs(self.df, "g", "y")
        self.out = table(self.res, "pairwise")

    def test_two_by_k_pairs_are_not_dropped(self):
        self.assertEqual(len(self.out), 3, "3 个水平应有 3 对")
        self.assertTrue((self.out["levels_compared"] == 3).all())

    def test_each_pair_matches_scipy_and_bonferroni(self):
        full = pd.crosstab(self.df["g"], self.df["y"])
        for _, row in self.out.iterrows():
            a, b = [s.strip() for s in row["pair"].split("vs")]
            _, p, _, _ = stats.chi2_contingency(full.loc[[a, b]], correction=False)
            self.assertRounded(row["p_raw"], p, nd=5)
            self.assertRounded(row["p_adj"], min(1.0, p * 3), nd=5)


# --------------------------------------------------------------------------- #
# 5-6. t tests
# --------------------------------------------------------------------------- #
class TTestTest(Base):
    def setUp(self):
        rng = np.random.default_rng(6)
        self.a = rng.normal(10, 2, 80)
        self.b = rng.normal(10.6, 2.4, 90)
        self.df = pd.DataFrame({"v": np.r_[self.a, self.b], "g": ["A"] * 80 + ["B"] * 90})

    def test_independent_t_d_and_ci(self):
        test = table(ML.t_test_independent(self.df, "v", "g"), "test")
        lev = stats.levene(self.a, self.b)
        equal = lev.pvalue >= ALPHA
        t, p = stats.ttest_ind(self.a, self.b, equal_var=equal)
        self.assertRounded(col(test, "levene_p").iloc[0], lev.pvalue, nd=6)
        self.assertRounded(col(test, "t").iloc[0], t)
        self.assertRounded(col(test, "p").iloc[0], p, nd=6)
        self.assertEqual(bool(col(test, "equal_var").iloc[0]), bool(equal))
        n1, n2 = len(self.a), len(self.b)
        sp2 = ((n1 - 1) * self.a.var(ddof=1) + (n2 - 1) * self.b.var(ddof=1)) / (n1 + n2 - 2)
        self.assertRounded(col(test, "cohens_d").iloc[0],
                           (self.a.mean() - self.b.mean()) / math.sqrt(sp2), nd=4)
        diff = self.a.mean() - self.b.mean()
        v1 = self.a.var(ddof=1) / n1
        v2 = self.b.var(ddof=1) / n2
        se = math.sqrt(v1 + v2)
        if equal:
            dof = n1 + n2 - 2
        else:  # Welch–Satterthwaite
            dof = (v1 + v2) ** 2 / (v1 ** 2 / (n1 - 1) + v2 ** 2 / (n2 - 1))
        half = float(stats.t.ppf(0.975, dof)) * se
        self.assertRounded(col(test, "mean_diff_ci_low").iloc[0], diff - half, nd=3)
        self.assertRounded(col(test, "mean_diff_ci_high").iloc[0], diff + half, nd=3)

    def test_paired_t_matches_scipy_and_reports_pearson_r(self):
        rng = np.random.default_rng(7)
        before = rng.normal(5, 1, 60)
        after = before + rng.normal(0.4, 0.8, 60)
        row = table(ML.t_test_paired(pd.DataFrame({"b": before, "a": after}), "b", "a"),
                    "paired")
        t, p = stats.ttest_rel(before, after)
        self.assertRounded(col(row, "t").iloc[0], t)
        self.assertRounded(col(row, "p").iloc[0], p, nd=6)
        self.assertRounded(col(row, "correlation").iloc[0],
                           np.corrcoef(before, after)[0, 1])
        self.assertRounded(col(row, "mean_diff").iloc[0], (before - after).mean())
        self.assertRounded(col(row, "cohens_dz").iloc[0],
                           (before - after).mean() / (before - after).std(ddof=1))

    def test_three_groups_is_refused_with_a_usable_message(self):
        df = pd.DataFrame({"v": [1.0, 2, 3, 4, 5, 6], "g": ["A", "A", "B", "B", "C", "C"]})
        with self.assertRaises(ML.MethodError) as ctx:
            ML.t_test_independent(df, "v", "g")
        self.assertIn("方差分析", str(ctx.exception))


# --------------------------------------------------------------------------- #
# 7. ANOVA + post-hoc
# --------------------------------------------------------------------------- #
class AnovaTest(Base):
    def setUp(self):
        rng = np.random.default_rng(8)
        self.g = rng.choice(["A", "B", "C"], 150)
        self.v = rng.normal(0, 1, 150) + pd.Series(self.g).map({"A": 0, "B": 0.7, "C": 1.5}).values
        self.df = pd.DataFrame({"v": self.v, "g": self.g})
        self.groups = [self.v[self.g == k] for k in ["A", "B", "C"]]

    def test_f_eta2_levene_and_welch(self):
        res = ML.anova(self.df, "v", "g")
        F, p = stats.f_oneway(*self.groups)
        self.assertRounded(res.stats["F"], F)
        self.assertRounded(res.stats["p"], p, nd=6)
        grand = self.v.mean()
        ssb = sum(len(x) * (x.mean() - grand) ** 2 for x in self.groups)
        sst = ((self.v - grand) ** 2).sum()
        self.assertRounded(res.stats["eta2"], ssb / sst, nd=6)
        atab = table(res, "anova")
        self.assertRounded(col(atab, "levene_p").iloc[0],
                           stats.levene(*self.groups).pvalue, nd=6)
        from statsmodels.stats.oneway import anova_oneway
        self.assertRounded(col(atab, "welch_p").iloc[0],
                           anova_oneway(self.groups, use_var="unequal").pvalue, nd=6)

    def test_posthoc_is_lsd_with_pooled_mse(self):
        # 事后比较用的是合并组内方差（LSD），不是 Welch 的逐对标准误；
        # 两条路径必须明确区分，否则"和 scipy 对不上"会被误判成 bug。
        out = table(ML.posthoc(self.df, "v", "g"), "posthoc")
        n_total, k = len(self.v), 3
        mse = sum((len(g) - 1) * g.var(ddof=1) for g in self.groups) / (n_total - k)
        self.assertEqual(len(out), 3)
        for _, row in out.iterrows():
            a, b = [s.strip() for s in row["pair"].split("vs")]
            x, y = self.v[self.g == a], self.v[self.g == b]
            se = math.sqrt(mse * (1 / len(x) + 1 / len(y)))
            t = (x.mean() - y.mean()) / se
            p = 2 * stats.t.sf(abs(t), n_total - k)
            self.assertRounded(row["se"], se, nd=4)
            self.assertRounded(row["t"], t, nd=4)
            self.assertRounded(row["p_raw"], p, nd=6)
            self.assertRounded(row["p_adj"], min(1.0, p * 3), nd=6)

    def test_posthoc_says_which_method_and_flags_unequal_variance(self):
        res = ML.posthoc(self.df, "v", "g")
        joined = " ".join(res.verdict)
        self.assertIn("LSD", joined)
        if stats.levene(*self.groups).pvalue < ALPHA:
            self.assertIn("Levene", joined)


# --------------------------------------------------------------------------- #
# 8. non-parametric
# --------------------------------------------------------------------------- #
class NonParametricTest(Base):
    def setUp(self):
        rng = np.random.default_rng(9)
        self.a = rng.normal(0, 1, 70)
        self.b = rng.normal(0.5, 1.3, 80)
        self.df = pd.DataFrame({"v": np.r_[self.a, self.b], "g": ["A"] * 70 + ["B"] * 80})

    def test_kruskal_matches_scipy_and_epsilon2(self):
        rng = np.random.default_rng(10)
        df = pd.DataFrame({"v": rng.normal(0, 1, 150), "g": rng.choice(["A", "B", "C"], 150)})
        res = ML.kruskal(df, "v", "g")
        groups = [df.loc[df["g"] == k, "v"] for k in ["A", "B", "C"]]
        H, p = stats.kruskal(*groups)
        self.assertRounded(res.stats["H"], H)
        self.assertRounded(res.stats["p"], p, nd=6)
        self.assertRounded(col(table(res, "kruskal"), "epsilon2").iloc[0],
                           (H - 3 + 1) / (len(df) - 3))

    def test_mannwhitney_u_and_rank_biserial_sign(self):
        row = table(ML.mannwhitney(self.df, "v", "g"), "test")
        u, p = stats.mannwhitneyu(self.a, self.b, alternative="two-sided")
        self.assertRounded(col(row, "U").iloc[0], u, nd=4)
        self.assertRounded(col(row, "p").iloc[0], p, nd=6)
        # 约定：r>0 表示 levels[0] 的秩更高（取值更大）。这里 b 整体更大，
        # 而 levels[0] 是 "A"（较小的一组），所以 r 必须为负——符号是能被读者
        # 拿去做方向判断的量，写反了不会报错，只会让结论反过来。
        rb = 2 * u / (len(self.a) * len(self.b)) - 1
        self.assertRounded(col(row, "rank_biserial").iloc[0], rb)
        self.assertLess(rb, 0)
        # 把较大的那组放在前面（levels[0] 由出现顺序决定），r 必须翻正：
        # 只换标签不换数值是测不到方向的（标签换了，值没换）。
        big_first = pd.DataFrame({"v": np.r_[self.b, self.a],
                                  "g": ["A"] * len(self.b) + ["B"] * len(self.a)})
        self.assertGreater(
            table(ML.mannwhitney(big_first, "v", "g"), "test")["rank_biserial"].iloc[0], 0)

    def test_wilcoxon_matches_scipy(self):
        rng = np.random.default_rng(11)
        before = rng.normal(3, 1, 50)
        after = before + rng.normal(0.5, 0.7, 50)
        row = table(ML.wilcoxon(pd.DataFrame({"b": before, "a": after}), "b", "a"), "test")
        stat, p = stats.wilcoxon(before, after)
        self.assertRounded(col(row, "W").iloc[0], stat, nd=4)
        self.assertRounded(col(row, "p").iloc[0], p, nd=6)
        self.assertRounded(col(row, "median_diff").iloc[0], np.median(before - after))


# --------------------------------------------------------------------------- #
# 9. correlation
# --------------------------------------------------------------------------- #
class CorrelationTest(Base):
    def test_pearson_matches_scipy(self):
        rng = np.random.default_rng(12)
        x = rng.normal(0, 1, 100)
        y = 0.6 * x + rng.normal(0, 1, 100)
        row = table(ML.correlation(pd.DataFrame({"x": x, "y": y}), ["x", "y"],
                                   method="pearson"), "correlations")
        r, p = stats.pearsonr(x, y)
        self.assertRounded(col(row, "r").iloc[0], r)
        self.assertRounded(col(row, "p").iloc[0], p, nd=6)
        self.assertEqual(col(row, "direction").iloc[0], "正")

    def test_spearman_when_forced(self):
        rng = np.random.default_rng(13)
        x = rng.normal(0, 1, 100)
        y = np.exp(x) + rng.normal(0, 1, 100)
        row = table(ML.correlation(pd.DataFrame({"x": x, "y": y}), ["x", "y"],
                                   method="spearman"), "correlations")
        self.assertRounded(col(row, "r").iloc[0], stats.spearmanr(x, y).statistic)

    def test_auto_falls_back_to_spearman_for_one_skewed_variable(self):
        rng = np.random.default_rng(14)
        df = pd.DataFrame({"x": rng.normal(0, 1, 200), "y": rng.lognormal(0, 1.2, 200)})
        self.assertEqual(ML.correlation(df, ["x", "y"], method="auto").stats["method"],
                         "spearman")


# --------------------------------------------------------------------------- #
# 10. OLS
# --------------------------------------------------------------------------- #
class LinearRegressionTest(Base):
    def setUp(self):
        rng = np.random.default_rng(15)
        n = 180
        self.x1 = rng.normal(0, 1, n)
        self.x2 = 0.4 * self.x1 + rng.normal(0, 1, n)
        self.y = 1.5 + 0.8 * self.x1 - 0.5 * self.x2 + rng.normal(0, 1, n)
        self.df = pd.DataFrame({"y": self.y, "x1": self.x1, "x2": self.x2})
        res = ML.linear_regression(self.df, "y", ["x1", "x2"])
        self.coef = table(res, "coefficients").set_index("term")
        self.model = table(res, "model")
        X = np.column_stack([np.ones(n), self.x1, self.x2])
        self.beta = np.linalg.lstsq(X, self.y, rcond=None)[0]
        self.resid = self.y - X @ self.beta
        self.X = X

    def test_beta_matches_lstsq(self):
        self.assertRounded(self.coef.loc["x1", "beta"], self.beta[1])
        self.assertRounded(self.coef.loc["x2", "beta"], self.beta[2])

    def test_hc1_standard_error_by_hand(self):
        X, resid = self.X, self.resid
        n, k = X.shape
        inv = np.linalg.inv(X.T @ X)
        meat = sum((resid[i] ** 2) * np.outer(X[i], X[i]) for i in range(n))
        se = np.sqrt(np.diag(inv @ meat @ inv * n / (n - k)))
        self.assertRounded(self.coef.loc["x1", "se"], se[1])
        self.assertRounded(self.coef.loc["x2", "se"], se[2])
        self.assertRounded(self.coef.loc["x1", "t"], self.beta[1] / se[1], nd=3)
        p = 2 * stats.t.sf(abs(self.beta[1] / se[1]), n - k)
        self.assertRounded(self.coef.loc["x1", "p"], p, nd=6)

    def test_r2_dw_and_std_beta(self):
        sst = ((self.y - self.y.mean()) ** 2).sum()
        self.assertRounded(col(self.model, "r2").iloc[0],
                           1 - (self.resid ** 2).sum() / sst, nd=4)
        self.assertRounded(col(self.model, "durbin_watson").iloc[0],
                           (np.diff(self.resid) ** 2).sum() / (self.resid ** 2).sum(),
                           nd=3)
        self.assertRounded(self.coef.loc["x2", "std_beta"],
                           self.beta[2] * self.x2.std(ddof=1) / self.y.std(ddof=1))

    def test_vif_is_one_over_one_minus_auxiliary_r2(self):
        X = np.column_stack([np.ones(len(self.x1)), self.x2])
        b = np.linalg.lstsq(X, self.x1, rcond=None)[0]
        resid = self.x1 - X @ b
        r2 = 1 - (resid ** 2).sum() / ((self.x1 - self.x1.mean()) ** 2).sum()
        self.assertAlmostEqual(self.coef.loc["x1", "vif"], round(1 / (1 - r2), 3),
                               places=3)


# --------------------------------------------------------------------------- #
# 11. logistic
# --------------------------------------------------------------------------- #
class LogisticTest(Base):
    def setUp(self):
        rng = np.random.default_rng(16)
        n = 300
        self.x = rng.normal(0, 1, n)
        self.y = (rng.random(n) < 1 / (1 + np.exp(-(-0.8 + 1.1 * self.x)))).astype(int)
        res = ML.logistic(pd.DataFrame({"y": self.y, "x": self.x}), "y", ["x"])
        self.coef = table(res, "coefficients").set_index("term")
        self.model = table(res, "model")

    def test_or_and_ci_match_statsmodels(self):
        fit = sm.Logit(self.y, sm.add_constant(self.x)).fit(disp=False)
        lo, hi = fit.conf_int()[1]
        self.assertRounded(self.coef.loc["x", "B"], fit.params[1])
        self.assertAlmostEqual(self.coef.loc["x", "OR"], math.exp(fit.params[1]),
                               places=2)
        self.assertAlmostEqual(self.coef.loc["x", "OR_ci_low"], math.exp(lo), places=2)
        self.assertAlmostEqual(self.coef.loc["x", "OR_ci_high"], math.exp(hi), places=2)

    def test_mcfadden_and_lr_chi2(self):
        fit = sm.Logit(self.y, sm.add_constant(self.x)).fit(disp=False)
        p0 = self.y.mean()
        ll0 = float(np.sum(self.y * np.log(p0) + (1 - self.y) * np.log(1 - p0)))
        self.assertRounded(col(self.model, "mcfadden_r2").iloc[0], 1 - fit.llf / ll0)
        lr = 2 * (fit.llf - ll0)
        self.assertRounded(col(self.model, "llr_chi2").iloc[0], lr, nd=2)
        self.assertRounded(col(self.model, "llr_p").iloc[0],
                           float(stats.chi2.sf(lr, 1)), nd=6)

    def test_epv_warning_when_events_are_few(self):
        rng = np.random.default_rng(17)
        df = pd.DataFrame({"y": [1] * 8 + [0] * 92, "x": rng.normal(0, 1, 100)})
        res = ML.logistic(df, "y", ["x"])
        self.assertTrue(any("EPV" in n for n in res.notes), f"notes 里应有 EPV：{res.notes}")

    def test_non_binary_outcome_is_refused(self):
        df = pd.DataFrame({"y": [0, 1, 2] * 20, "x": np.arange(60.0)})
        with self.assertRaises(ML.MethodError):
            ML.logistic(df, "y", ["x"])


# --------------------------------------------------------------------------- #
# 12. factor analysis / PCA
# --------------------------------------------------------------------------- #
class FactorTest(Base):
    def setUp(self):
        rng = np.random.default_rng(18)
        n = 300
        f1, f2 = rng.normal(0, 1, n), rng.normal(0, 1, n)
        cols = {}
        for i in range(3):
            cols[f"a{i}"] = 0.8 * f1 + rng.normal(0, 0.6, n)
            cols[f"b{i}"] = 0.8 * f2 + rng.normal(0, 0.6, n)
        self.df = pd.DataFrame(cols)
        self.cols = list(self.df.columns)

    def test_full_extraction_reproduces_the_correlation_matrix(self):
        # 取满 k 个成分时，L L' 必须精确等于相关矩阵（主成分法的定义）。
        res = ML.efa(self.df, self.cols, n_factors=len(self.cols), rotate="none")
        load = table(res, "loadings")
        L = load[[c for c in load.columns if c.startswith("F")]].values
        self.assertTrue(np.allclose(L @ L.T, self.df.corr().values, atol=5e-3))

    def test_two_factors_leave_only_the_discarded_variance(self):
        res = ML.efa(self.df, self.cols, n_factors=2, rotate="none")
        load = table(res, "loadings")
        L = load[[c for c in load.columns if c.startswith("F")]].values
        R = self.df.corr().values
        off = ~np.eye(R.shape[0], dtype=bool)
        # 被丢掉的特征值之和决定残差大小，残差不能为 0，但必须与 θ_k+1..θ_p 相符
        eig = np.linalg.eigvalsh(R)[::-1]
        self.assertLess(float(np.abs((R - L @ L.T)[off]).max()), 0.35)
        self.assertGreater(float(eig[2:].sum()), 0.0)

    def test_communality_is_sum_of_squared_loadings(self):
        load = table(ML.efa(self.df, self.cols, n_factors=2), "loadings")
        L = load[[c for c in load.columns if c.startswith("F")]].values
        self.assertTrue(np.allclose(load["communality"].values,
                                    (L ** 2).sum(axis=1), atol=5e-3))

    def test_silhouette_on_a_big_sample_is_a_finite_estimate(self):
        """n>5000 时返回 NaN 会让判定读成"结构弱，K 可能不合适"。

        5100 行、三个相距 8 个标准差的簇，是任何算法都该判"清晰"的数据。
        这里把抽样上限压到 60，只验证"抽样而不是放弃"。
        """
        rng = np.random.default_rng(5)
        centers = np.array([[0, 0], [8, 0], [0, 8]])
        X = np.vstack([rng.normal(c, 0.4, (1700, 2)) for c in centers])
        labels = np.repeat([0, 1, 2], 1700)
        sil = ML._silhouette(X, labels, max_n=60)
        self.assertTrue(np.isfinite(sil), "大样本不应返回 NaN")
        self.assertGreater(sil, 0.5)

    def test_describe_does_not_treat_a_missing_test_as_normal(self):
        """n>5000 超出 Shapiro 适用范围，normality_p=None 不能被当成"正态通过"。"""
        rng = np.random.default_rng(6)
        df = pd.DataFrame({"v": rng.exponential(1.0, 6000)})  # skew≈2
        row = table(ML.describe(df), "descriptive").iloc[0]
        self.assertIn("中位数", str(row["report"]))
        self.assertNotIn("均值±标准差", str(row["report"]))

    def test_efa_reports_rotated_variance_separately(self):
        """旋转会重新分配方差：旋转后那三列必须与旋转后的载荷一致。"""
        rng = np.random.default_rng(7)
        f1 = rng.normal(size=400)
        f2 = rng.normal(size=400)
        df = pd.DataFrame({
            "a1": f1 + rng.normal(0, .3, 400), "a2": f1 + rng.normal(0, .3, 400),
            "a3": f1 + rng.normal(0, .3, 400),
            "b1": f2 + rng.normal(0, .3, 400), "b2": f2 + rng.normal(0, .3, 400),
            "b3": f2 + rng.normal(0, .3, 400)})
        res = ML.efa(df, list(df.columns), n_factors=2)
        load = table(res, "loadings").set_index("variable")
        var = table(res, "variance")
        # 逐因子比：只比总和抓不住"用未旋转特征值冒充"这一变异，
        # 因为主成分法下保留 k 个因子的载荷平方和总和恒等于前 k 个特征值之和。
        for j, col in enumerate(("F1", "F2")):
            ss_j = float((load[col] ** 2).sum())
            self.assertAlmostEqual(float(var["ss_loading_rotated"].iloc[j]), ss_j, places=2)
            self.assertAlmostEqual(float(var["variance_pct_rotated"].iloc[j]),
                                   ss_j / len(df.columns) * 100, places=1)

    def test_eigenvalues_match_correlation_matrix(self):
        var = table(ML.efa(self.df, self.cols, n_factors=2), "variance")
        eig = np.linalg.eigvalsh(self.df.corr().values)[::-1]
        self.assertTrue(np.allclose(var["eigenvalue"].values, eig[:2], atol=1e-2))
        self.assertAlmostEqual(var["cumulative_pct"].iloc[-1],
                               100 * eig[:2].sum() / eig.sum(), places=1)

    def test_kmo_is_a_fraction_and_bartlett_matches_formula(self):
        kb = ML.kmo_bartlett(self.df, self.cols)
        self.assertGreater(kb["kmo"], 0.0)
        self.assertLessEqual(kb["kmo"], 1.0)
        R = self.df.corr().values
        n, p = len(self.df), len(self.cols)
        want = -(n - 1 - (2 * p + 5) / 6) * math.log(np.linalg.det(R))
        self.assertAlmostEqual(kb["bartlett_chi2"], want, delta=0.05)

    def test_pca_variance_shares(self):
        res = ML.pca(self.df, self.cols, n_components=2)
        eig = np.linalg.eigvalsh(self.df.corr().values)[::-1]
        self.assertAlmostEqual(table(res, "variance")["variance_pct"].iloc[0],
                               100 * eig[0] / eig.sum(), places=1)
        self.assertAlmostEqual(res.stats["pc1_pct"], 100 * eig[0] / eig.sum(), places=1)

    def test_pca_loadings_are_correlations_with_the_components(self):
        """载荷 = 特征向量×sqrt(特征值) = corr(x, PC)；拿单位特征向量当载荷，
        数值相差 0.59 与 0.90 这个量级，所有"载荷>0.4 才解释"的判断都会错。"""
        res = ML.pca(self.df, self.cols, n_components=2)
        load = table(res, "loadings").set_index("variable")
        Z = (self.df[self.cols] - self.df[self.cols].mean()) / self.df[self.cols].std(ddof=1)
        U, S, Vt = np.linalg.svd(Z.values, full_matrices=False)
        scores = U[:, :2] * S[:2]
        for j in range(2):
            want = [float(np.corrcoef(Z[c].values, scores[:, j])[0, 1])
                    for c in self.cols]
            for c, w in zip(self.cols, want):
                self.assertAlmostEqual(float(load.loc[c, f"PC{j + 1}"]), w, places=2)


# --------------------------------------------------------------------------- #
# 13. reliability
# --------------------------------------------------------------------------- #
class CronbachTest(Base):
    def setUp(self):
        rng = np.random.default_rng(19)
        f = rng.normal(0, 1, 200)
        self.df = pd.DataFrame({f"q{i}": np.round(3 + 0.8 * f + rng.normal(0, 0.5, 200))
                                for i in range(1, 6)})
        self.res = ML.cronbach(self.df, list(self.df.columns))
        self.rel = table(self.res, "reliability")

    def test_alpha_matches_the_hand_formula(self):
        k = self.df.shape[1]
        want = k / (k - 1) * (1 - self.df.var(ddof=1).sum()
                              / self.df.sum(axis=1).var(ddof=1))
        self.assertAlmostEqual(self.res.stats["alpha"], want, places=3)

    def test_item_total_r_is_corrected_for_overlap(self):
        total = self.df.sum(axis=1)
        for i, column in enumerate(self.df.columns):
            want = np.corrcoef(self.df[column], total - self.df[column])[0, 1]
            self.assertAlmostEqual(self.rel["item_total_r"].iloc[i], want, places=3,
                                   msg=f"{column} 的 item-total r 应该是校正后的相关")

    def test_alpha_if_deleted_drops_the_column(self):
        sub = self.df.drop(columns=["q1"])
        want = ML.cronbach(sub, list(sub.columns)).stats["alpha"]
        self.assertAlmostEqual(self.rel["alpha_if_deleted"].iloc[0], want, places=3)


# --------------------------------------------------------------------------- #
# 14. clustering
# --------------------------------------------------------------------------- #
class ClusterTest(Base):
    def test_kmeans_profile_is_in_original_units(self):
        rng = np.random.default_rng(20)
        df = pd.DataFrame({"收入": rng.normal(8000, 1500, 150),
                           "年龄": rng.normal(40, 8, 150)})
        res = ML.kmeans_analysis(df, ["收入", "年龄"], k=2)
        prof = table(res, "profile").set_index("cluster")
        zprof = table(res, "profile_z").set_index("cluster")
        self.assertTrue(4000 < prof["收入"].min() < 12000,
                        f"中心应在收入量级，实际 {prof['收入'].tolist()}")
        sd, mu = df.std(ddof=1), df.mean()
        back = zprof[["收入", "年龄"]].values * sd.values + mu.values
        self.assertTrue(np.allclose(back, prof[["收入", "年龄"]].values, atol=2.0),
                        "profile_z × sd + mean 必须等于 profile")

    def test_silhouette_matches_hand_computation(self):
        rng = np.random.default_rng(21)
        df = pd.DataFrame({"a": rng.normal(0, 1, 60), "b": rng.normal(5, 1, 60)})
        res = ML.kmeans_analysis(df, ["a", "b"], k=2)
        zprof = table(res, "profile_z")[["a", "b"]].values
        X = ((df - df.mean()) / df.std(ddof=1)).values
        # 分配样本用的是 z 分数中心；拿原始单位 profile 去比会分空一簇。
        labels = np.argmin(((X[:, None, :] - zprof[None, :, :]) ** 2).sum(-1), axis=1)
        D = np.sqrt(((X[:, None, :] - X[None, :, :]) ** 2).sum(-1))
        sil = []
        for i in range(len(X)):
            same = labels == labels[i]
            if same.sum() <= 1:
                sil.append(0.0)
                continue
            a = D[i, same].sum() / (same.sum() - 1)
            b = min(D[i, labels == u].mean() for u in np.unique(labels) if u != labels[i])
            sil.append((b - a) / max(a, b) if max(a, b) else 0.0)
        self.assertAlmostEqual(res.stats["silhouette"], float(np.mean(sil)), places=2)

    def test_hclust_sizes_and_cophenetic(self):
        rng = np.random.default_rng(22)
        df = pd.DataFrame({"a": rng.normal(0, 1, 80), "b": rng.normal(0, 1, 80)})
        res = ML.hclust(df, ["a", "b"], k=3)
        self.assertEqual(int(table(res, "sizes")["n"].sum()), 80)
        self.assertTrue(0 < res.stats["cophenetic"] <= 1)


# --------------------------------------------------------------------------- #
# 15. discriminant analysis
# --------------------------------------------------------------------------- #
class LdaTest(Base):
    def test_wilks_lambda_is_det_w_over_det_t(self):
        rng = np.random.default_rng(23)
        g = np.array(["X"] * 45 + ["Y"] * 45)
        a = np.r_[rng.normal(0, 1, 45), rng.normal(1.6, 1, 45)]
        b = np.r_[rng.normal(0, 1, 45), rng.normal(1.0, 1, 45)]
        df = pd.DataFrame({"g": g, "a": a, "b": b})
        res = ML.lda(df, "g", ["a", "b"])
        X = np.column_stack([a, b])
        W = np.zeros((2, 2))
        B = np.zeros((2, 2))
        mu = X.mean(axis=0)
        for k in ["X", "Y"]:
            Xi = X[g == k]
            m = Xi.mean(axis=0)
            W += (Xi - m).T @ (Xi - m)
            B += len(Xi) * np.outer(m - mu, m - mu)
        want = np.linalg.det(W) / np.linalg.det(W + B)
        self.assertAlmostEqual(res.stats["wilks"], want, places=3)
        self.assertGreater(res.stats["accuracy"], 0.5)
        self.assertLessEqual(res.stats["accuracy"], 1.0)


# --------------------------------------------------------------------------- #
# 16. time series
# --------------------------------------------------------------------------- #
class TimeSeriesTest(Base):
    def test_arima_order_is_the_aic_argmin(self):
        rng = np.random.default_rng(24)
        n = 120
        v = np.zeros(n)
        for t in range(1, n):
            v[t] = 0.6 * v[t - 1] + rng.normal(0, 1)
        res = ML.time_series(pd.DataFrame({"t": np.arange(n), "v": v}), "t", "v")
        best = None
        for p in range(0, 3):
            for d in (0, 1):
                try:
                    aic = float(sm.tsa.ARIMA(v, order=(p, d, 0)).fit().aic)
                except Exception:
                    continue
                if best is None or aic < best[0]:
                    best = (aic, p, d)
        self.assertEqual((res.stats["p"], res.stats["d"]), (best[1], best[2]))
        self.assertAlmostEqual(res.stats["aic"], best[0], delta=0.05)

    def test_ljungbox_p_is_in_range(self):
        rng = np.random.default_rng(24)
        n = 100
        v = np.cumsum(rng.normal(0, 1, n))
        res = ML.time_series(pd.DataFrame({"t": np.arange(n), "v": v}), "t", "v")
        p = col(table(res, "fit"), "ljungbox_p").iloc[0]
        self.assertGreaterEqual(float(p), 0.0)
        self.assertLessEqual(float(p), 1.0)


# --------------------------------------------------------------------------- #
# 17. mediation
# --------------------------------------------------------------------------- #
class MediationTest(Base):
    def setUp(self):
        rng = np.random.default_rng(25)
        n = 200
        self.x = rng.normal(0, 1, n)
        self.m = 0.5 * self.x + rng.normal(0, 1, n)
        self.y = 0.4 * self.x + 0.7 * self.m + rng.normal(0, 1, n)
        self.res = ML.mediation(pd.DataFrame({"x": self.x, "m": self.m, "y": self.y}),
                                "x", "m", "y", n_boot=200)
        self.paths = table(self.res, "paths")
        self.effect = table(self.res, "effect")

    def _coef(self, marker):
        row = self.paths[self.paths["path"].str.contains(marker, regex=False)]
        return float(row["coef"].iloc[0]), float(row["se"].iloc[0])

    def test_indirect_equals_a_times_b(self):
        a, _ = self._coef("(a)")
        b, _ = self._coef("(b)")
        self.assertAlmostEqual(self.res.stats["indirect"], a * b, places=4)

    def test_sobel_z_matches_the_formula(self):
        a, sa = self._coef("(a)")
        b, sb = self._coef("(b)")
        want = a * b / math.sqrt(a ** 2 * sb ** 2 + b ** 2 * sa ** 2)
        self.assertAlmostEqual(col(self.effect, "sobel_z").iloc[0], want, places=2)
        self.assertAlmostEqual(col(self.effect, "sobel_p").iloc[0],
                               float(2 * stats.norm.sf(abs(want))), places=4)

    def test_bootstrap_interval_is_ordered_and_brackets_indirect(self):
        lo, hi = self.res.stats["boot_lo"], self.res.stats["boot_hi"]
        self.assertLess(lo, hi)
        self.assertTrue(lo < self.res.stats["indirect"] < hi)


# --------------------------------------------------------------------------- #
# 18. Kano
# --------------------------------------------------------------------------- #
class KanoTest(Base):
    #: 教材（Berger et al. 1993）的 5×5 表，独立于实现抄一遍：
    #: 行=功能题答案，列=反功能题答案，1=不喜欢 3=无所谓 5=喜欢。
    KANO_TABLE = {
        (5, 1): "O", (5, 2): "A", (5, 3): "A", (5, 4): "A", (5, 5): "Q",
        (4, 1): "M", (4, 2): "I", (4, 3): "I", (4, 4): "I", (4, 5): "R",
        (3, 1): "M", (3, 2): "I", (3, 3): "I", (3, 4): "I", (3, 5): "R",
        (2, 1): "M", (2, 2): "I", (2, 3): "I", (2, 4): "I", (2, 5): "R",
        (1, 1): "Q", (1, 2): "R", (1, 3): "R", (1, 4): "R", (1, 5): "R",
    }

    def test_kano_lookup_matches_the_textbook_table_cell_by_cell(self):
        for (f, d), want in self.KANO_TABLE.items():
            self.assertEqual(ML._kano_category(f, d), want,
                             f"({f},{d}) 应为 {want}")
        # 25 个格子必须全覆盖，没有靠兜底"猜"的格子
        self.assertEqual(len(self.KANO_TABLE), 25)

    def test_kano_counts_better_worse_and_reverse_exclusion(self):
        f = [5, 4, 3, 1, 5, 2, 1, 5]
        d = [1, 2, 4, 5, 5, 3, 4, 3]
        row = table(ML.kano(pd.DataFrame({"f": f, "d": d}), {"需求A": ("f", "d")}),
                    "kano").iloc[0]
        cats = [ML._kano_category(int(a), int(b)) for a, b in zip(f, d)]
        self.assertEqual(int(row["A"]) + int(row["O"]) + int(row["M"]) + int(row["I"])
                         + int(row["R"]) + int(row["Q"]), len(f))
        valid = sum(1 for c in cats if c in "AOIM")
        self.assertEqual(int(row["valid"]), valid)
        self.assertAlmostEqual(row["better"],
                               (cats.count("A") + cats.count("O")) / valid, places=3)
        self.assertAlmostEqual(row["worse"],
                               -(cats.count("O") + cats.count("M")) / valid, places=3)
        self.assertLessEqual(row["worse"], 0.0)

    def test_reverse_answers_do_not_dilute_the_coefficient(self):
        # R（反向）只在 f、d 都落在中间带时出现（f=1,d=3）；f=1,d=1 是无差异 I。
        df = pd.DataFrame({"f": [5] * 20 + [1] * 20, "d": [1] * 20 + [3] * 20})
        row = table(ML.kano(df, {"x": ("f", "d")}), "kano").iloc[0]
        self.assertAlmostEqual(row["better"], 1.0, places=3)
        self.assertEqual(int(row["excluded"]), 20)


# --------------------------------------------------------------------------- #
# 19. refusals and delegation
# --------------------------------------------------------------------------- #
class RefusalTest(Base):
    def test_sem_refuses_instead_of_pretending(self):
        with self.assertRaises(ML.MethodError) as ctx:
            ML.sem(model="x -> y")
        self.assertIn("SEM", str(ctx.exception).upper())

    def test_validity_reuses_efa_and_states_its_limit(self):
        rng = np.random.default_rng(26)
        f = rng.normal(0, 1, 120)
        df = pd.DataFrame({f"q{i}": np.round(3 + 0.8 * f + rng.normal(0, .4, 120))
                           for i in range(1, 5)})
        res = ML.validity(df, list(df.columns), n_factors=1)
        self.assertIn("loadings", [t[0] for t in res.tables])
        self.assertIn("内容效度", " ".join(res.verdict))


# --------------------------------------------------------------------------- #
# 20. design matrix and p-value rendering
# --------------------------------------------------------------------------- #
class DesignAndRenderingTest(Base):
    def test_categorical_predictor_becomes_k_minus_one_dummies(self):
        df = pd.DataFrame({"g": ["甲", "乙", "丙"] * 10, "x": np.arange(30.0)})
        _, names = ML._design(df, ["g", "x"])
        self.assertEqual(sum(1 for n in names if n.startswith("g_")), 2)
        self.assertIn("x", names)

    def test_p_values_never_render_as_zero(self):
        md = MP._md_table(pd.DataFrame({"p": [1e-12, 0.0421, 0.5]}))
        self.assertIn("<.001", md)
        self.assertNotIn("0.000", md)
        self.assertIn("0.042", md)


if __name__ == "__main__":
    unittest.main(verbosity=2)