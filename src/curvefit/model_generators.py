"""
All classes of model generators should have a model_function that takes arguments
df and times and returns predictions at those times.

**NOTE**: This is useful for the predictive validity functions that need a fit_model
function that takes those arguments. That callable will be generated with the model_function in these classes.
"""

from copy import deepcopy
from curvefit.model import CurveModel
from curvefit.forecaster import Forecaster
from curvefit.pv import PVModel
from curvefit.utils import convex_combination, model_average


class ModelPipeline:
    """
    Base class for a model generator.
    If a model needs to have initial parameters started for the predictive validity,
    put that in run_init_model
    """
    def __init__(self, all_data, col_t, col_obs, col_group, col_obs_compare, all_cov_names, fit_space, predict_space):
        """
        Base class for a model pipeline. At minimum needs the following arguments for a
        model pipeline.

        Args:
            all_data: (pd.DataFrame) of *all* the data that will go into this modeling pipeline
            col_t: (str) name of the column with time
            col_group: (str) name of the column with the group in it
            col_obs: (str) the name of the column with observations for fitting the model
            col_obs_compare: (str) the name of the column that will be used for predictive validity comparison
            all_cov_names: List[str] list of name(s) of covariate(s). Not the same as the covariate specifications
                that are required by CurveModel in order of parameters. You should exclude intercept from this list.
            fit_space: (callable) the space to fit in, one of curvefit.functions
            predict_space: (callable) the space to do predictive validity in, one of curvefit.functions
        """
        self.all_data = all_data
        self.col_t = col_t
        self.col_group = col_group
        self.col_obs = col_obs
        self.col_obs_compare = col_obs_compare
        self.all_cov_names = all_cov_names
        self.fit_space = fit_space
        self.predict_space = predict_space

        self.pv = None
        self.forecaster = None
        self.draws = None
        self.simulated_data = None

    def setup_pipeline(self):
        """
        Sets up the pipeline for running predictive validity and forecasting data out.
        Should be run at the end of the inheriting class' init so that the self.generate()
        gets the model settings to be run for all models.
        """
        self.pv = PVModel(
            data=self.all_data,
            col_t=self.col_t,
            col_group=self.col_group,
            col_obs=self.col_obs,
            col_obs_compare=self.col_obs_compare,
            predict_space=self.predict_space,
            model_generator=self.generate()
        )
        self.forecaster = Forecaster(
            data=self.all_data,
            col_t=self.col_t,
            col_group=self.col_group,
            col_obs=self.col_obs_compare,
            all_cov_names=self.all_cov_names
        )

    def run_init_model(self):
        """
        Runs the model that doesn't need to be run multiple times.
        """
        self.refresh()

    def refresh(self):
        """
        Clear the current model results.
        """
        pass

    def generate(self):
        """
        Generate a copy of this class.
        """
        return deepcopy(self)

    def fit(self, df):
        """
        Function to fit the model with a given data frame.
        Args:
            df: (pd.DataFrame)
        """
        pass

    def predict(self, times, predict_space, predict_group='all'):
        """
        Function to create predictions based on the model fit.
        Args:
            times: (np.array) of times to predict at
            predict_space: (callable) curvefit.functions function to predict in that space
            predict_group: which group to make predictions for
        """
        pass

    def run_predictive_validity(self, theta):
        """
        Run predictive validity for the full model.

        Args:
            theta: amount of scaling for residuals relative to prediction.
        """
        self.pv.run_pv(theta=theta)

    # TODO: Fix this so that it's accurately translating based on self.fit_space and self.predict_space
    def translate_predict_space_to_fit_space(self, predictions):
        return predictions

    def create_draws(self, smoothed_radius, num_draws, num_forecast_out, prediction_times):
        """
        Generate draws for a model pipeline, smoothing over a neighbor radius of residuals
        for far out and num data points.

        Args:
            smoothed_radius: List[int] 2-element list of amount of smoothing for the residuals
            num_draws: (int) the number of draws to take
            num_forecast_out: (int) how far out into the future should residual simulations be taken
            prediction_times: (int) which times to produce final predictions at
        """
        if self.pv.all_residuals is None:
            raise RuntimeError("Need to first run predictive validity with self.run_predictive_validity.")

        self.forecaster.fit_residuals(
            residual_data=self.pv.get_smoothed_residuals(radius=smoothed_radius),
            mean_outcome='residual_mean',
            std_outcome='residual_std',
            covariates=['far_out', 'num_data'],
            residual_model_type='linear'
        )

        mean_prediction = self.predict(times=prediction_times, predict_space=self.predict_space)
        self.simulated_data = self.forecaster.simulate(
            out=num_forecast_out, fit_space=self.fit_space,
            predictions=mean_prediction
        )

        self.draws = []
        for i in range(num_draws):
            print(f"Creating {i}th draw.")
            generator = self.generate()
            generator.refresh()
            generator.fit(df=self.simulated_data[i])
            predictions = generator.predict(times=prediction_times, predict_space=self.predict_space)
            self.draws.append(predictions)

        return self


class BasicModel(ModelPipeline):
    def __init__(self, fit_dict, basic_model_dict, **pipeline_kwargs):
        """
        Generic class for a function to produce predictions from a model
        with the following attributes.

        Args:
            **pipeline_kwargs: keyword arguments for the base class of ModelPipeline
            predict_group: (str) which group to make predictions for
            fit_dict: keyword arguments to CurveModel.fit_params()
            basic_model_dict: additional keyword arguments to the CurveModel class
                col_obs_se: (str) of observation standard error
                col_covs: List[str] list of names of covariates to put on the parameters
            param_names (list{str}):
                Names of the parameters in the specific functional form.
            link_fun (list{function}):
                List of link functions for each parameter.
            var_link_fun (list{function}):
                List of link functions for the variables including fixed effects
                and random effects.
        """
        super().__init__(**pipeline_kwargs)
        self.fit_dict = fit_dict
        self.basic_model_kwargs = basic_model_dict
        self.basic_model_kwargs.update(**pipeline_kwargs)
        self.mod = None

        self.setup_pipeline()

    def refresh(self):
        self.mod = None

    def fit(self, df):
        self.mod = CurveModel(df=df, **self.basic_model_kwargs)
        self.mod.fit_params(**self.fit_dict, smart_initialize=True)

    def predict(self, times, predict_space, predict_group='all'):
        predictions = self.mod.predict(
            t=times, group_name=predict_group,
            prediction_functional_form=predict_space
        )
        return predictions


class TightLooseBetaPModel(ModelPipeline):
    def __init__(self, loose_beta_fit_dict, tight_beta_fit_dict,
                 loose_p_fit_dict, tight_p_fit_dict, basic_model_dict,
                 beta_model_extras=None, p_model_extras=None,
                 blend_start_t=2, blend_end_t=30,
                 **pipeline_kwargs):
        """
        Produces two tight-loose models as a convex combination between the two of them,
        and then averages

        Args:
            **pipeline_kwargs: keyword arguments for the base class of ModelPipeline

            loose_beta_fit_dict: dictionary of keyword arguments to CurveModel.fit_params() for the loose beta model
            tight_beta_fit_dict: dictionary of keyword arguments to CurveModel.fit_params() fro the tight beta model
            loose_p_fit_dict: dictionary of keyword arguments to CurveModel.fit_params() for the loose p model
            tight_p_fit_dict: dictionary of keyword arguments to CurveModel.fit_params() fro the tight p model

            basic_model_dict: additional keyword arguments to the CurveModel class
                col_obs_se: (str) of observation standard error
                col_covs: List[str] list of names of covariates to put on the parameters
            param_names (list{str}):
                Names of the parameters in the specific functional form.
            link_fun (list{function}):
                List of link functions for each parameter.
            var_link_fun (list{function}):
                List of link functions for the variables including fixed effects
                and random effects.
            beta_model_extras: (optional) dictionary of keyword arguments to
                override the basic_model_kwargs for the beta model
            p_model_extras: (optional) dictionary of keyword arguments to
                override the basic_model_kwargs for the p model
            blend_start_t: (int) the time to start blending tight and loose
            blend_end_t: (int) the time to stop blending tight and loose
        """
        super().__init__(**pipeline_kwargs)

        self.basic_model_dict = basic_model_dict
        self.basic_model_dict.update(**pipeline_kwargs)
        self.beta_model_kwargs = self.basic_model_dict
        self.p_model_kwargs = self.basic_model_dict

        if beta_model_extras is not None:
            self.beta_model_kwargs = self.beta_model_kwargs.update(beta_model_extras)

        if p_model_extras is not None:
            self.p_model_kwargs = self.p_model_kwargs.update(p_model_extras)

        self.loose_beta_fit_dict = loose_beta_fit_dict
        self.tight_beta_fit_dict = tight_beta_fit_dict
        self.loose_p_fit_dict = loose_p_fit_dict
        self.tight_p_fit_dict = tight_p_fit_dict

        self.blend_start_t = blend_start_t
        self.blend_end_t = blend_end_t

        self.loose_beta_model = None
        self.tight_beta_model = None
        self.loose_p_model = None
        self.tight_p_model = None

        self.setup_pipeline()

    def refresh(self):
        self.loose_beta_model = None
        self.tight_beta_model = None
        self.loose_p_model = None
        self.tight_p_model = None

    def fit(self, df):
        self.loose_beta_model = CurveModel(df=df, **self.beta_model_kwargs)
        self.tight_beta_model = CurveModel(df=df, **self.beta_model_kwargs)
        self.loose_p_model = CurveModel(df=df, **self.p_model_kwargs)
        self.tight_p_model = CurveModel(df=df, **self.p_model_kwargs)

        self.loose_beta_model.fit_params(**self.loose_beta_fit_dict)
        self.tight_beta_model.fit_params(**self.tight_beta_fit_dict)
        self.loose_p_model.fit_params(**self.loose_p_fit_dict)
        self.tight_p_model.fit_params(**self.tight_p_fit_dict)

    def predict(self, times, predict_space, predict_group='all'):
        loose_beta_predictions = self.loose_beta_model.predict(
            t=times, group_name=predict_group,
            prediction_functional_form=predict_space
        )
        tight_beta_predictions = self.tight_beta_model.predict(
            t=times, group_name=predict_group,
            prediction_functional_form=predict_space
        )
        loose_p_predictions = self.loose_p_model.predict(
            t=times, group_name=predict_group,
            prediction_functional_form=predict_space
        )
        tight_p_predictions = self.tight_p_model.predict(
            t=times, group_name=predict_group,
            prediction_functional_form=predict_space
        )
        beta_predictions = convex_combination(
            t=times, pred1=tight_beta_predictions, pred2=loose_beta_predictions,
            pred_fun=predict_space, start_day=self.blend_start_t, end_day=self.blend_end_t
        )
        p_predictions = convex_combination(
            t=times, pred1=tight_p_predictions, pred2=loose_p_predictions,
            pred_fun=predict_space, start_day=self.blend_start_t, end_day=self.blend_end_t
        )
        averaged_predictions = model_average(
            pred1=beta_predictions, pred2=p_predictions,
            w1=0.5, w2=0.5, pred_fun=predict_space
        )
        return averaged_predictions