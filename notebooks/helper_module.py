"""Helper module to process simulation data.

Cotains the following data structures:
- Logfile: read and analyze simulation log-files

"""

import pandas as pd
import numpy as np
import matplotlib.tri as tri
import pickle
import torch

# parameters for uniform plot appearance
alpha_contour = 0.75
fontsize_contour = 14
fontsize_label = 24
fontsize_legend = 20
fontsize_tick = 20
figure_width = 16
line_width = 3

# make torch results reproducible and use double precision
torch.set_default_tensor_type(torch.DoubleTensor)
torch.manual_seed(42)
np.random.seed(42)


def transform_polar_2D(px, py):
    """Transform 2D Cartesian to polar coordinates.

    Parameters
    ----------
    px, py - array-like : x and y coordinate of points to transform

    Returns
    -------
    rad, phi array-like : corresponding polar coordinates

    """
    rad = np.sqrt(np.square(px) + np.square(py))
    phi = np.arccos(py / rad)
    return rad, phi


class Logfile():
    """Load and evaluate simulation log-files."""

    def __init__(self, path=None):
        """Initialize a Logfile object.

        Parameters
        ----------
        path - String : path to the log-file

        """
        self.path = path

    def read_logfile(self, usecols=None):
        """Read log-file from source.abs

        Parameters
        ----------
        usecols - List : list of columns to use as String

        """
        try:
            self.log = pd.read_csv(self.path, sep=',', usecols=usecols)
            print("Successfully read file \033[1m{}\033[0m".format(self.path))
        except Exception as general_exception:
            print("Error reading file \033[1m{}\033[0m".format(self.path))
            print(str(general_exception))

    def get_profile(self, x_axis=None, y_axis=None):
        """Get x-y-profile, e.g. for plotting y over x.

        Parameters
        ----------
        x_axis - String : column name for the first variable
        y_axis - String : column name for the second variable

        Returns
        -------
        x, y

        """
        return self.log[x_axis].values, self.log[y_axis].values

    def apply_to_range(self, range_name, start, end, value_name, function):
        """Apply function to values in a given range.

        A typical use would be to compute the average velocity between t=10 and
        t=15:
        range_name = "time"
        start = 10
        end = 15
        value_name = "u_x"
        function = np.mean

        Parameters
        ----------
        range_name - String : name of column which determines the range
        start - float       : start of range to consider
        end - float         : end of range to consider
        value_name - String : column on which to apply the function
        function - Function : function to apply to the extracted values

        Returns
        -------
        function(value)

        """
        values = self.log[(self.log[range_name] >= start) & (self.log[range_name] <= end)]
        return function(values[value_name].values)

    def get_min_max(self, range_name, start, end, value_name):
        """Get min and max of value_name in a given range.

        Parameters
        ----------
        range_name - String : name of column that determines the range
        start - Float       : start of range
        end - Float         : end of range
        value_name - String : name of column where to compute min and max

        Returns
        -------
        min_val, max_val

        """
        values = self.log[(self.log[range_name] >= start) & (self.log[range_name] <= end)]
        return np.amin(values[value_name].values), np.amax(values[value_name].values)

    def find_closest(self, value_name, value):
        """Find row where the value of value_name is closest to value.

        Parameters
        ----------
        value_name - String : name of the column to search in
        value - Float       : value to search for

        Returns
        -------
        row

        """
        row = self.log.iloc[(self.log[value_name] - value).abs().argsort()[:1]]
        return row


class CenterFieldValues2D():
    def __init__(self, path=None, center=None, u_b=None):
        """Initialize CenterFieldValue2D object.

        Parameters
        ----------
        path - String : path to data file
        center - array-like : [x,y] coordinates of the center of mass
        U_b - array-like : [u_x, u_y] components of the bubble rise velocity

        """
        self.path = path
        self.center = center
        self.u_b = u_b
        self.read_field()
        self.create_triangulation()

    def read_field(self):
        """Read center values from disk."""
        try:
            names = ['f', 'ref', 'u_x', 'u_y', 'u_z', 'x', 'y', 'z']
            usecols = ['f', 'u_x', 'u_y', 'x', 'y']
            self.data = pd.read_csv(self.path, sep=',', header=0, names=names, usecols=usecols)
            print("Successfully read file \033[1m{}\033[0m".format(self.path))
        except Exception as read_exc:
            print("Error reading data from disk for file \033[1m{}\033[0m".format(self.path))
            print(str(read_exc))

    def create_triangulation(self):
        """Create a triangulation from points."""
        self.triang = tri.Triangulation(
            self.data['x'].values-self.center[0],
            self.data['y'].values-self.center[1])

    def interpolate_velocity(self, xi, yi, relative=False, magnitude=True):
        """Interpolate velocity at given points.

        Parameters
        ----------
        xi, yi - array-like : x and y coordinates of interpolation points
        relative - Boolean : compute velocity relative to u_b if True
        magnitude - Boolean : return magnitude of vector if True

        Returns
        -------
        u_xi, u_yi - array-like : interpolated velocity components
        mag(u_i) - array-like : magnitude of interpolated velocity

        """
        interpolator_u_x = tri.CubicTriInterpolator(
            self.triang, self.data['u_x'].values, kind='geom')
        interpolator_u_y = tri.CubicTriInterpolator(
            self.triang, self.data['u_y'].values, kind='geom')
        u_xi = interpolator_u_x(xi, yi)
        u_yi = interpolator_u_y(xi, yi)
        if relative:
            u_xi -= self.u_b[1] # paraview bug, see further down
            u_yi -= self.u_b[0]

        if magnitude:
            return np.sqrt(np.square(u_xi) + np.square(u_yi))
        else:
            return u_yi, u_xi  # paraview bug: the transform filter does not swap the vector components

    def interpolate_volume_fraction(self, xi, yi):
        """Interpolate volume fraction at given points.

        Parameters
        ----------
        xi, yi - array-like : x and y coordinates of interpolation points

        Returns
        -------
        f - array-like : interpolated volume fraction

        """
        self.interpolator_f = tri.CubicTriInterpolator(
            self.triang, self.data['f'].values, kind='geom')
        return self.interpolator_f(xi, yi)


class FacetCollection2D():
    """Read and evaluate geometrical properties of PLIC facets."""

    def __init__(self, path, origin, flip_xy):
        """Initialize FacetCollection2D object.

        Parameters
        ----------
        path - String : path to facet data
        origin - array-like : [x, y] coordinates of the origin
        flip_xy - Boolean : flip x and y coordinate if True

        Members
        -------
        facets - array-like : [N_facets*2, 2] array with x and y coordinates
            of intersection points (facet intersection with background mesh);
            two consective elements form a facet, e.g. [:2,:] is the first facet
        facet_centers - array-like : [N_facets, 2] array with x and y
            coordinates of facet centers
        facet_normals - array-like : [N_facets, 2] array with nx and ny
            components (unit length)
        facet_tangentials - array-like : [N_facets, 2] array with tx and ty
            components (unit length)

        """
        self.path = path
        self.origin = origin
        self.flip_xy = flip_xy
        self.facets = None
        self.facet_centers = None
        self.facet_normals = None
        self.facet_tangentials = None
        self.read_facets()

    def read_facets(self):
        """Read facets from disk."""
        try:
            with open(self.path, "rb") as file:
                self.facets = pickle.load(file)
            self.facets.drop(["element"], axis=1, inplace=True)
            if self.flip_xy:
                self.facets.rename(columns={"px":"py", "py":"px"}, inplace=True)
            print("Successfully read file \033[1m{}\033[0m".format(self.path))
        except Exception as read_exc:
            print("Error reading data from disk for file \033[1m{}\033[0m".format(self.path))
            print(str(read_exc))

    def get_facets(self, polar=False):
        """Return the intersection points of facets and background mesh.

        Paramters
        ---------
        polar - Boolean : transform to polar coordinates if True

        Returns
        -------
        p_x, p_y - array-like : x and y coordinates of intersection points
        rad, phi - array-like : polar coordinates if polar is True

        """
        px = self.facets.px.values - self.origin[0]
        py = self.facets.py.values - self.origin[1]
        if polar:
            return transform_polar_2D(px, py)
        else:
            return px, py


class SimpleMLP(torch.nn.Module):
    """Implements a standard MLP with otional batch normalization.
    """
    def __init__(self, **kwargs):
        """Create a SimpleMLP object derived from torch.nn.Module.

        Parameters
        ----------
        n_inputs - Integer : number of features/inputs
        n_outputs - Integer : number of output values
        n_layers - Integer : number of hidden layers
        activation - Function : nonlinearity/activation function
        batch_norm - Boolean : use batch normalization instead of bias if True

        Members
        -------
        layers - List : list with network layers and activations

        """
        super().__init__()
        self.n_inputs = kwargs.get("n_inputs", 1)
        self.n_outputs = kwargs.get("n_outputs", 1)
        self.n_layers = kwargs.get("n_layers", 1)
        self.n_neurons = kwargs.get("n_neurons", 10)
        self.activation = kwargs.get("activation", torch.sigmoid)
        self.batch_norm = kwargs.get("batch_norm", True)
        self.layers = torch.nn.ModuleList()

        if self.batch_norm:
            # input layer to first hidden layer
            self.layers.append(torch.nn.Linear(self.n_inputs, self.n_neurons*2, bias=False))
            self.layers.append(torch.nn.BatchNorm1d(self.n_neurons*2))
            # add more hidden layers if specified
            if self.n_layers > 2:
                for hidden in range(self.n_layers-2):
                    self.layers.append(torch.nn.Linear(self.n_neurons*2, self.n_neurons*2, bias=False))
                    self.layers.append(torch.nn.BatchNorm1d(self.n_neurons*2))
            self.layers.append(torch.nn.Linear(self.n_neurons*2, self.n_neurons, bias=False))
            self.layers.append(torch.nn.BatchNorm1d(self.n_neurons))
        else:
            # input layer to first hidden layer
            self.layers.append(torch.nn.Linear(self.n_inputs, self.n_neurons))
            # add more hidden layers if specified
            if self.n_layers > 1:
                for hidden in range(self.n_layers-1):
                    self.layers.append(torch.nn.Linear(self.n_neurons, self.n_neurons))
        # last hidden layer to output layer
        self.layers.append(torch.nn.Linear(self.n_neurons, self.n_outputs))
        print("Created model with {} weights.".format(self.model_parameters()))

    def forward(self, x):
        """Compute forward pass through model.

        Parameters
        ----------
        x - array-like : feature vector with dimension [n_samples, n_inputs]

        Returns
        -------
        output - array-like : model output with dimension [n_samples, n_outputs]

        """
        if self.batch_norm:
            for i_layer in range(len(self.layers)-1):
                if isinstance(self.layers[i_layer], torch.nn.Linear):
                    x = self.layers[i_layer](x)
                else:
                    x = self.activation(self.layers[i_layer](x))
        else:
            for i_layer in range(len(self.layers)-1):
                x = self.activation(self.layers[i_layer](x))
        return self.layers[-1](x)

    def model_parameters(self):
        """Compute total number of trainable model parameters."""
        return sum(p.numel() for p in self.parameters() if p.requires_grad)