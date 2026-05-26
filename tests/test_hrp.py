"""Unit tests for HRP _in_cluster and hrp_weights."""
import unittest
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage
from scipy.spatial.distance import squareform
from strategies.long_term import _in_cluster, hrp_weights


class TestInCluster(unittest.TestCase):
    """Verify the _in_cluster helper traverses the linkage tree correctly."""

    def setUp(self):
        np.random.seed(42)
        n = 100
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        self.prices = pd.DataFrame(
            np.random.randn(n, 4).cumsum(axis=0) * 0.5 + 100,
            columns=["A", "B", "C", "D"],
            index=dates,
        )

    def test_in_cluster_finds_leaf(self):
        """A leaf should always find itself."""
        returns = self.prices.pct_change().dropna()
        corr = returns.corr().values
        dist = np.sqrt(2 * (1 - corr))
        dist[np.diag_indices_from(dist)] = 0
        link = linkage(squareform(dist, checks=False), method="ward")

        for leaf in range(4):
            self.assertTrue(_in_cluster(link, leaf, leaf))

    def test_in_cluster_different_leaf_not_found(self):
        """A leaf should not find a different leaf directly."""
        returns = self.prices.pct_change().dropna()
        corr = returns.corr().values
        dist = np.sqrt(2 * (1 - corr))
        dist[np.diag_indices_from(dist)] = 0
        link = linkage(squareform(dist, checks=False), method="ward")

        # Leaf 0 should not equal leaf 1
        self.assertFalse(_in_cluster(link, 0, 1))

    def test_every_leaf_in_some_cluster(self):
        """Every leaf should be found when starting from the root cluster."""
        returns = self.prices.pct_change().dropna()
        corr = returns.corr().values
        dist = np.sqrt(2 * (1 - corr))
        dist[np.diag_indices_from(dist)] = 0
        link = linkage(squareform(dist, checks=False), method="ward")

        n = 4
        root = n + len(link) - 1
        for leaf in range(n):
            self.assertTrue(
                _in_cluster(link, leaf, root),
                f"leaf {leaf} not found from root cluster {root}",
            )


class TestHRPWeights(unittest.TestCase):
    """Verify HRP produces valid portfolio weights."""

    def setUp(self):
        np.random.seed(42)
        n = 200
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        self.prices = pd.DataFrame(
            np.random.randn(n, 5).cumsum(axis=0) * 0.5 + 100,
            columns=["X1", "X2", "X3", "X4", "X5"],
            index=dates,
        )

    def test_weights_sum_to_one(self):
        w = hrp_weights(self.prices)
        self.assertAlmostEqual(sum(w.values()), 1.0, places=4)
        self.assertEqual(len(w), 5)

    def test_all_weights_positive(self):
        w = hrp_weights(self.prices)
        for v in w.values():
            self.assertGreater(v, 0)

    def test_insufficient_data_fallback(self):
        short = self.prices.iloc[:30]
        w = hrp_weights(short)
        self.assertAlmostEqual(sum(w.values()), 1.0, places=4)
        # Should be equal weight
        for v in w.values():
            self.assertAlmostEqual(v, 0.2, places=2)

    def test_different_linkage_methods(self):
        for method in ["ward", "single", "complete", "average"]:
            w = hrp_weights(self.prices, method=method)
            self.assertAlmostEqual(sum(w.values()), 1.0, places=4)

    def test_different_shrinkage_methods(self):
        for shrinkage in ["ledoit_wolf", "oas", "sample"]:
            w = hrp_weights(self.prices, shrinkage=shrinkage)
            self.assertAlmostEqual(sum(w.values()), 1.0, places=4)


if __name__ == "__main__":
    unittest.main()
