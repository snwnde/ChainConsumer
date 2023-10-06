import logging
from enum import Enum
from pathlib import Path

import numpy as np
from pydantic import Field
from scipy.integrate import simps
from scipy.interpolate import interp1d
from scipy.ndimage.filters import gaussian_filter

from .base import BetterBase
from .chain import Chain, ChainName, ColumnName, MaxPosterior, Named2DMatrix
from .helpers import get_grid_bins, get_latex_table_frame, get_smoothed_bins
from .kde import MegKDE


class SummaryStatistic(Enum):
    MAX = "max"
    MEAN = "mean"
    CUMULATIVE = "cumulative"
    MAX_SYMMETRIC = "max_symmetric"
    MAX_SHORTEST = "max_shortest"
    MAX_CENTRAL = "max_central"


class Bound(BetterBase):
    lower: float | None = Field(default=None)
    center: float | None = Field(default=None)
    upper: float | None = Field(default=None)


class Analysis:
    def __init__(self, parent: "ChainConsumer"):
        self.parent = parent
        self._logger = logging.getLogger("chainconsumer")

        self._summaries = {
            SummaryStatistic.MAX: self.get_parameter_summary_max,
            SummaryStatistic.MEAN: self.get_parameter_summary_mean,
            SummaryStatistic.CUMULATIVE: self.get_parameter_summary_cumulative,
            SummaryStatistic.MAX_SYMMETRIC: self.get_paramater_summary_max_symmetric,
            SummaryStatistic.MAX_SHORTEST: self.get_parameter_summary_max_shortest,
            SummaryStatistic.MAX_CENTRAL: self.get_parameter_summary_max_central,
        }

    def get_latex_table(
        self,
        columns: list[str] | int | None = None,
        transpose: bool = False,
        caption: str | None = None,
        label: str = "tab:model_params",
        hlines: bool = True,
        blank_fill: str = "--",
        filename: str | Path | None = None,
    ) -> str:  # pragma: no cover
        """Generates a LaTeX table from parameter summaries.

        Args:
            columns : list[str], int optional
                A list of what parameters to include in the table. By default, includes all columns.
                If an integer is passed, will include the first N columns.
            transpose : bool, optional
                Defaults to False, which gives each column as a parameter, each chain (framework)
                as a row. You can swap it so that you have a parameter each row and a framework
                each column by setting this to True
            caption : str, optional
                If you want to generate a caption for the table through Python, use this.
                Defaults to an empty string
            label : str, optional
                If you want to generate a label for the table through Python, use this.
                Defaults to an empty string
            hlines : bool, optional
                Inserts ``\\hline`` before and after the header, and at the end of table.
            blank_fill : str, optional
                If a framework does not have a particular parameter, will fill that cell of
                the table with this string.
            filename : str | Path, optional
                The file to save the output string to

        Returns:
            str: the LaTeX table.
        """
        if columns is None:
            columns = self.parent.all_columns
        elif isinstance(columns, int):
            columns = self.parent.all_columns[:columns]
        # TODO: ensure labels are a thin we can add
        num_parameters = len(columns)

        chains = self.parent.chains
        num_chains = len(chains)
        fit_values = self.get_summary(chains=chains)
        if label is None:
            label = ""
        if caption is None:
            caption = ""

        end_text = " \\\\ \n"
        column_text = "c" * (num_chains + 1) if transpose else "c" * (num_parameters + 1)

        center_text = ""
        hline_text = "\\hline\n"
        if hlines:
            center_text += hline_text + "\t\t"
        if transpose:
            center_text += " & ".join(["Parameter"] + [c.name for c in chains.values()]) + end_text
            if hlines:
                center_text += "\t\t" + hline_text
            for p in columns:
                arr = ["\t\t" + self.parent.get_label(p)]
                for _, column_results in fit_values.items():
                    if p in column_results:
                        arr.append(self.get_parameter_text(column_results[p], wrap=True))
                    else:
                        arr.append(blank_fill)
                center_text += " & ".join(arr) + end_text
        else:
            center_text += " & ".join(["Model", *[self.parent.get_label(c) for c in columns]]) + end_text
            if hlines:
                center_text += "\t\t" + hline_text
            for name, chain_res in fit_values.items():
                arr = ["\t\t" + name]
                for p in columns:
                    if p in chain_res:
                        arr.append(self.get_parameter_text(chain_res[p], wrap=True))
                    else:
                        arr.append(blank_fill)
                center_text += " & ".join(arr) + end_text
        if hlines:
            center_text += "\t\t" + hline_text
        final_text = get_latex_table_frame(caption, label) % (column_text, center_text)

        if filename is not None:
            if isinstance(filename, str):
                filename = Path(filename)
            with Path.open(filename, "w") as f:
                f.write(final_text)

        return final_text

    def get_summary(
        self,
        columns: list[str] | None = None,
        chains: dict[str, Chain] | list[str] | None = None,
    ) -> dict[ChainName, dict[ColumnName, Bound]]:
        """Gets a summary of the marginalised parameter distributions.

        Args:
            parameters (list[str], optional): A list of parameters which to generate summaries for.
            chains (dict[str, Chain] | list[str], optional): A list of chains to generate summaries for.

        Returns:
            dict[ChainName, dict[ColumnName, Bound]]: A map from chain name to column name to bound.
        """
        results = {}
        if chains is None:
            chains = self.parent.chains
        if isinstance(chains, list):
            chains = {c: self.parent.chains[c] for c in chains}

        for name, chain in chains.items():
            res = {}
            params_to_find = columns if columns is not None else chain.samples.columns
            for p in params_to_find:
                if p not in chain.samples:
                    continue
                summary = self.get_parameter_summary(chain, p)
                res[p] = summary
            results[name] = res

        return results

    def get_max_posteriors(self, chains: dict[str, Chain] | list[str] | None = None) -> dict[ChainName, MaxPosterior]:
        """Gets the maximum posterior point in parameter space from the passed parameters.

        Requires the chains to have set `posterior` values.

        Args:
            chains (dict[str, Chain] | list[str], optional): A list of chains to generate summaries for.

        Returns:
            dict[ChainName, MaxPosterior]: A map from chain name to max posterior point.
        """

        results = {}
        if chains is None:
            chains = self.parent.chains
        if isinstance(chains, list):
            chains = {c: self.parent.chains[c] for c in chains}

        for chain_name, chain in chains.items():
            max_posterior = chain.get_max_posterior_point()
            if max_posterior is None:
                continue
            results[chain_name] = max_posterior

        return results

    def get_parameter_summary(self, chain, parameter):
        # Ensure config has been called so we get the statistics set in config
        if not self.parent._configured:
            self.parent.configure_overrides()
        callback = self._summaries[chain.config["statistics"]]
        return chain.get_summary(parameter, callback)

    def get_correlation_table(
        self,
        chain: str | Chain,
        columns: list[str] | None = None,
        caption: str = "Parameter Correlations",
        label: str = "tab:parameter_correlations",
    ) -> str:
        """
        Gets a LaTeX table of parameter correlations.

        Args:
        chain (str|Chain, optional_: The chain index or name. Defaults to first chain.
        columns (list[str], optional): The list of parameters to compute correlations. Defaults to all columns
        caption (str, optional): The LaTeX table caption.
        label (str, optional): The LaTeX table label.

        Returns:
            str: The LaTeX table ready to go!
        """
        if isinstance(chain, str):
            assert chain in self.parent.chains, f"Chain {chain} not found!"
            chain = self.parent.chains[chain]
        if chain is None:
            assert len(self.parent.chains) == 1, "You must specify a chain if there are multiple chains"
            chain = next(iter(self.parent.chains.values()))

        correlations = chain.get_correlation(columns=columns)
        return self._get_2d_latex_table(correlations, caption, label)

    def get_covariance_table(
        self,
        chain: str | Chain,
        columns: list[str] | None = None,
        caption: str = "Parameter Covariance",
        label: str = "tab:parameter_covariance",
    ) -> str:
        """
        Gets a LaTeX table of parameter covariances.

        Args:
        chain (str|Chain, optional_: The chain index or name. Defaults to first chain.
        columns (list[str], optional): The list of parameters to compute covariances on. Defaults to all columns
        caption (str, optional): The LaTeX table caption.
        label (str, optional): The LaTeX table label.

        Returns:
            str: The LaTeX table ready to go!
        """
        if isinstance(chain, str):
            assert chain in self.parent.chains, f"Chain {chain} not found!"
            chain = self.parent.chains[chain]
        if chain is None:
            assert len(self.parent.chains) == 1, "You must specify a chain if there are multiple chains"
            chain = next(iter(self.parent.chains.values()))

        covariance = chain.get_covariance(columns=columns)
        return self._get_2d_latex_table(covariance, caption, label)

    def _get_smoothed_histogram(self, chain, parameter, pad=False):
        data = chain.get_data(parameter)
        smooth = chain.config["smooth"]
        if chain.grid:
            bins = get_grid_bins(data)
        else:
            bins = chain.config["bins"]
            bins, smooth = get_smoothed_bins(smooth, bins, data, chain.weights, pad=pad)

        hist, edges = np.histogram(data, bins=bins, density=True, weights=chain.weights)
        if chain.power is not None:
            hist = hist**chain.power
        edge_centers = 0.5 * (edges[1:] + edges[:-1])
        xs = np.linspace(edge_centers[0], edge_centers[-1], 10000)

        if smooth:
            hist = gaussian_filter(hist, smooth, mode="reflect")
        kde = chain.config["kde"]
        if kde:
            kde_xs = np.linspace(edge_centers[0], edge_centers[-1], max(200, int(bins.max())))
            ys = MegKDE(data, chain.weights, factor=kde).evaluate(kde_xs)
            area = simps(ys, x=kde_xs)
            ys = ys / area
            ys = interp1d(kde_xs, ys, kind="linear")(xs)
        else:
            ys = interp1d(edge_centers, hist, kind="linear")(xs)
        cs = ys.cumsum()
        cs /= cs.max()
        return xs, ys, cs

    def _get_2d_latex_table(self, named_matrix: Named2DMatrix, caption: str, label: str):
        parameters = [self.parent.get_label(c) for c in named_matrix.columns]
        matrix = named_matrix.matrix
        latex_table = get_latex_table_frame(caption=caption, label=label)
        column_def = "c|%s" % ("c" * len(parameters))
        hline_text = "        \\hline\n"

        table = ""
        table += " & ".join(["", *parameters]) + "\\\\ \n"
        table += hline_text
        max_len = max([len(s) for s in parameters])
        format_string = "        %%%ds" % max_len
        for p, row in zip(parameters, matrix):
            table += format_string % p
            for r in row:
                table += " & %5.2f" % r
            table += " \\\\ \n"
        table += hline_text
        return latex_table % (column_def, table)

    def get_parameter_text(self, bound: Bound, wrap: bool = False):
        """Generates LaTeX appropriate text from marginalised parameter bounds.

        Parameters
        ----------
        lower : float
            The lower bound on the parameter
        maximum : float
            The value of the parameter with maximum probability
        upper : float
            The upper bound on the parameter
        wrap : bool
            Wrap output text in dollar signs for LaTeX

        Returns
        -------
        str
            The formatted text given the parameter bounds
        """
        if bound.lower is None or bound.upper is None or bound.center is None:
            return ""
        upper_error = bound.upper - bound.center
        lower_error = bound.center - bound.lower
        if upper_error != 0 and lower_error != 0:
            resolution = min(np.floor(np.log10(np.abs(upper_error))), np.floor(np.log10(np.abs(lower_error))))
        elif upper_error == 0 and lower_error != 0:
            resolution = np.floor(np.log10(np.abs(lower_error)))
        elif upper_error != 0 and lower_error == 0:
            resolution = np.floor(np.log10(np.abs(upper_error)))
        else:
            resolution = np.floor(np.log10(np.abs(bound.center)))
        factor = 0
        fmt = "%0.1f"
        r = 1
        if np.abs(resolution) > 2:
            factor = -resolution
        if resolution == 2:
            fmt = "%0.0f"
            factor = -1
            r = 0
        if resolution == 1:
            fmt = "%0.0f"
        if resolution == -1:
            fmt = "%0.2f"
            r = 2
        elif resolution == -2:
            fmt = "%0.3f"
            r = 3
        upper_error *= 10**factor
        lower_error *= 10**factor
        maximum = bound.center * 10**factor
        upper_error = round(upper_error, r)
        lower_error = round(lower_error, r)
        maximum = round(maximum, r)
        if maximum == -0.0:
            maximum = 0.0
        if resolution == 2:
            upper_error *= 10**-factor
            lower_error *= 10**-factor
            maximum *= 10**-factor
            factor = 0
            fmt = "%0.0f"
        upper_error_text = fmt % upper_error
        lower_error_text = fmt % lower_error
        if upper_error_text == lower_error_text:
            text = r"{}\pm {}".format(fmt, "%s") % (maximum, lower_error_text)
        else:
            text = r"{}^{{+{}}}_{{-{}}}".format(fmt, "%s", "%s") % (maximum, upper_error_text, lower_error_text)
        if factor != 0:
            text = r"\left( %s \right) \times 10^{%d}" % (text, -factor)
        if wrap:
            text = "$%s$" % text
        return text

    def get_parameter_summary_mean(self, chain, parameter):
        desired_area = chain.config["summary_area"]
        xs, _, cs = self._get_smoothed_histogram(chain, parameter)
        vals = [0.5 - desired_area / 2, 0.5, 0.5 + desired_area / 2]
        bounds = interp1d(cs, xs)(vals)
        bounds[1] = 0.5 * (bounds[0] + bounds[2])
        return bounds

    def get_parameter_summary_cumulative(self, chain, parameter):
        xs, _, cs = self._get_smoothed_histogram(chain, parameter)
        desired_area = chain.config["summary_area"]
        vals = [0.5 - desired_area / 2, 0.5, 0.5 + desired_area / 2]
        bounds = interp1d(cs, xs)(vals)
        return bounds

    def get_parameter_summary_max(self, chain, parameter):
        xs, ys, cs = self._get_smoothed_histogram(chain, parameter)
        desired_area = chain.config["summary_area"]
        n_pad = 1000
        x_start = xs[0] * np.ones(n_pad)
        x_end = xs[-1] * np.ones(n_pad)
        y_start = np.linspace(0, ys[0], n_pad)
        y_end = np.linspace(ys[-1], 0, n_pad)
        xs = np.concatenate((x_start, xs, x_end))
        ys = np.concatenate((y_start, ys, y_end))
        cs = ys.cumsum()
        cs = cs / cs.max()
        start_index = ys.argmax()
        max_val = ys[start_index]
        min_val = 0
        threshold = 0.003
        x1 = None
        x2 = None
        count = 0
        while x1 is None:
            mid = (max_val + min_val) / 2.0
            count += 1
            try:
                if count > 50:
                    raise ValueError("Failed to converge")
                i1 = start_index - np.where(ys[:start_index][::-1] < mid)[0][0]
                i2 = start_index + np.where(ys[start_index:] < mid)[0][0]
                area = cs[i2] - cs[i1]
                deviation = np.abs(area - desired_area)
                if deviation < threshold:
                    x1 = xs[i1]
                    x2 = xs[i2]
                elif area < desired_area:
                    max_val = mid
                elif area > desired_area:
                    min_val = mid
            except ValueError:
                self._logger.warning(f"Parameter {parameter} in chain {chain.name} is not constrained")
                return [None, xs[start_index], None]

        return [x1, xs[start_index], x2]

    def get_paramater_summary_max_symmetric(self, chain, parameter):
        xs, ys, cs = self._get_smoothed_histogram(chain, parameter)
        desired_area = chain.config["summary_area"]

        x_to_c = interp1d(xs, cs, bounds_error=False, fill_value=(0, 1))  # type: ignore

        # Get max likelihood x
        max_index = ys.argmax()
        x = xs[max_index]

        # Estimate width
        h = 0.5 * (xs[-1] - xs[0])
        prev_h = 0

        # Hone in on right answer
        while True:
            current_area = x_to_c(x + h) - x_to_c(x - h)
            if np.abs(current_area - desired_area) < 0.0001:
                return [x - h, x, x + h]
            temp = h
            h += 0.5 * np.abs(prev_h - h) * (1 if current_area < desired_area else -1)
            prev_h = temp

    def get_parameter_summary_max_shortest(self, chain, parameter):
        xs, ys, cs = self._get_smoothed_histogram(chain, parameter)
        desired_area = chain.config["summary_area"]

        c_to_x = interp1d(cs, xs, bounds_error=False, fill_value=(-np.inf, np.inf)) # type: ignore

        # Get max likelihood x
        max_index = ys.argmax()
        x = xs[max_index]

        # Pair each lower bound with an upper to get the right area
        x2 = c_to_x(cs + desired_area)
        dists = x2 - xs
        mask = (xs > x) | (x2 < x)  # Ensure max point is inside the area
        dists[mask] = np.inf
        ind = dists.argmin()
        return [xs[ind], x, x2[ind]]

    def get_parameter_summary_max_central(self, chain, parameter):
        xs, ys, cs = self._get_smoothed_histogram(chain, parameter)
        desired_area = chain.config["summary_area"]

        c_to_x = interp1d(cs, xs)

        # Get max likelihood x
        max_index = ys.argmax()
        x = xs[max_index]

        vals = [0.5 - 0.5 * desired_area, 0.5 + 0.5 * desired_area]
        xvals = c_to_x(vals)

        return [xvals[0], x, xvals[1]]


if __name__ == "__main__":
    from .chainconsumer import ChainConsumer
