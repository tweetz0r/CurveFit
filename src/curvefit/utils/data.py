import numpy as np


def data_translator(data, input_space, output_space,
                    threshold=1e-16):
    """Data translator, move data from one space to the other.

    Args:
        data (np.ndarray): data matrix or vector
        input_space (str | callable): input data space.
        output_space (str | callable): output data space.
        threshold (float, optional):
            Thresholding for the number below 0 in the linear space.

    Returns:
        np.ndarray:
            translated data.
    """
    if callable(input_space):
        input_space = input_space.__name__
    if callable(output_space):
        output_space = output_space.__name__

    total_space = ['gaussian_cdf', 'gaussian_pdf', 'ln_gaussian_cdf', 'ln_gaussian_pdf']

    assert input_space in total_space
    assert output_space in total_space
    assert isinstance(data, np.ndarray)
    assert threshold > 0.0

    data_ndim = data.ndim
    if data_ndim == 1:
        data = data[None, :]

    # thresholding the data in the linear space
    if input_space in ['gaussian_cdf', 'gaussian_pdf']:
        data = np.maximum(threshold, data)

    if input_space == output_space:
        output_data = data.copy()
    elif output_space == 'ln_' + input_space:
        output_data = np.log(data)
    elif input_space == 'ln_' + output_space:
        output_data = np.exp(data)
    elif 'gaussian_pdf' in input_space:
        if 'ln' in input_space:
            data = np.exp(data)
        output_data = np.cumsum(data, axis=1)
        if 'ln' in output_space:
            output_data = np.log(output_data)
    else:
        if 'ln' in input_space:
            data = np.exp(data)
        output_data = data - np.insert(data[:, :-1], 0, 0.0, axis=1)
        if 'ln' in output_space:
            output_data = np.log(output_data)

    # reverting the shape back if necessary
    if data_ndim == 1:
        output_data = output_data.ravel()

    return output_data