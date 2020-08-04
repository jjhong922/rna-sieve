import numpy as np
import scipy.linalg
from rnasieve.helper import compute_mixture_sigma, CLIP_VALUE

# Confidence Interval Computation


def _partial_mixture_variance_alpha(phi, sigma, alpha):
    return sigma + phi**2 - 2 * phi * (phi @ alpha.T)


def _partial_mixture_variance_phi(phi, alpha):
    return 2 * np.tile(alpha, (phi.shape[0], 1)) * (phi - phi @ alpha.T)


def _partial_alpha_alpha(phi, sigma, alpha, n):
    mixture_variance = compute_mixture_sigma(alpha, sigma, phi)
    partial_mv_alpha = _partial_mixture_variance_alpha(phi, sigma, alpha)
    return n * phi.T @ np.diag(1 / mixture_variance.reshape(-1)) @ phi + \
        partial_mv_alpha.T @ np.diag(
            1 / mixture_variance.reshape(-1)**2) @ partial_mv_alpha / 2


def _partial_phi_phi(phi, sigma, alpha, n, m):
    G, K = phi.shape
    mixture_variance = compute_mixture_sigma(alpha, sigma, phi)
    alpha_term = np.repeat(n * np.kron(alpha, alpha).reshape(K, K)[:, :, np.newaxis],
                           G, axis=2) / mixture_variance.reshape(1, 1, -1)
    partial_mv_phi = _partial_mixture_variance_phi(phi, alpha)
    phi_term = np.dstack([np.kron(partial_mv_phi[i], partial_mv_phi[i]).reshape(
        K, K) / (2 * mixture_variance[i]**2) for i in range(G)])
    return scipy.linalg.block_diag(*[np.squeeze(subarr) for subarr in np.dsplit(
        alpha_term + phi_term, G)]) + np.diag((m / sigma).reshape(-1))


def _partial_alpha_phi(phi, sigma, alpha, n):
    G, K = phi.shape
    mixture_variance = compute_mixture_sigma(alpha, sigma, phi)
    partial_mv_alpha = _partial_mixture_variance_alpha(phi, sigma, alpha)
    partial_mv_phi = _partial_mixture_variance_phi(phi, alpha)

    @np.vectorize
    def partial_alpha_phi_helper(i, j):
        g, k = j // K, j % K
        return n * alpha[0, k] * phi[g, i] / mixture_variance[g, 0] + \
            partial_mv_alpha[g, i] * partial_mv_phi[g, k] / \
            (2 * mixture_variance[g, 0]**2)

    return partial_alpha_phi_helper(*np.mgrid[0:K, 0:G * K])


def _partial_n_n(phi, sigma, alpha, n):
    mixture_variance = compute_mixture_sigma(alpha, sigma, phi)
    G = phi.shape[0]
    return (1 - G / 2) / n**2 + \
        np.sum((phi @ alpha.T)**2 / mixture_variance) / n


def _partial_alpha_n(phi, sigma, alpha, n):
    mixture_variance = compute_mixture_sigma(alpha, sigma, phi)
    partial_mv_alpha = _partial_mixture_variance_alpha(phi, sigma, alpha)
    return (phi / mixture_variance).T @ (phi @ alpha.T) + \
        np.sum(partial_mv_alpha / mixture_variance,
               axis=0).reshape(-1, 1) / (2 * n)


def _partial_n_phi(phi, sigma, alpha, n):
    mixture_variance = compute_mixture_sigma(alpha, sigma, phi)
    partial_mv_phi = _partial_mixture_variance_phi(phi, alpha)
    return (np.kron((phi @ alpha.T) / mixture_variance, alpha) +
            partial_mv_phi / (2 * n * mixture_variance)).reshape(1, -1)


def inverse_observed_fisher(phi, sigma, alpha, n, m):
    """Finds the inverse observed fisher information matrix.
    Returns an abbreviated square matrix of size K + 1
    where K is the number of cell types, to include the values
    for the inferred alpha and n values."""
    p_alpha_alpha = _partial_alpha_alpha(phi, sigma, alpha, n)
    p_n_n = _partial_n_n(phi, sigma, alpha, n)
    p_phi_phi = _partial_phi_phi(phi, sigma, alpha, n, m)
    p_alpha_phi = _partial_alpha_phi(phi, sigma, alpha, n)
    p_alpha_n = _partial_alpha_n(phi, sigma, alpha, n)
    p_n_phi = _partial_n_phi(phi, sigma, alpha, n)

    fisher_info = np.block([
        [p_alpha_alpha, p_alpha_n, p_alpha_phi],
        [p_alpha_n.T, p_n_n, p_n_phi],
        [p_alpha_phi.T, p_n_phi.T, p_phi_phi],
    ])

    inv_fisher = np.linalg.inv(fisher_info)
    return ((inv_fisher + inv_fisher.T) /
            2)[:alpha.shape[1] + 1, :alpha.shape[1] + 1]


def cross_protocol_inverse_observed_fisher(phi, sigma, m, alpha, psi, n):
    """Finds an adjusted inverse observed fisher information matrix
    for cross protocol experiments.

    Takes in phi, sigma, psi matrices filtered
    by filter_droplet_to_facs/filter_facs_to_droplet."""
    mixture_variance = compute_mixture_sigma(alpha, sigma, phi)
    z_scores = (phi @ alpha.T - psi / n) / np.sqrt(mixture_variance / n)
    z_tail = np.clip(
        np.count_nonzero(
            (z_scores > np.median(z_scores) + 2) |
            (z_scores < np.median(z_scores) - 2)),
        CLIP_VALUE,
        None)
    filter_length = np.min((np.round(3 * z_scores.shape[0] / z_tail), 300))
    filter_idxs = np.where(z_scores > np.quantile(
        z_scores, (z_scores.shape[0] - filter_length) / z_scores.shape[0]))[0]
    return inverse_observed_fisher(phi[filter_idxs], np.clip(
        sigma[filter_idxs], 1, None), alpha, n, m)