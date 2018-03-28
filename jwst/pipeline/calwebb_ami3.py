#!/usr/bin/env python
import logging

from .. import datamodels
from ..associations.load_as_asn import LoadAsAssociation
from ..stpipe import Pipeline


# step imports
from ..ami import ami_analyze_step
from ..ami import ami_average_step
from ..ami import ami_normalize_step
from ..model_blender import blendmeta

__version__ = '0.8.1'

# Define logging
log = logging.getLogger()
log.setLevel(logging.DEBUG)


class Ami3Pipeline(Pipeline):
    """
    Ami3Pipeline: Apply all level-3 calibration steps to an
    association of level-2b AMI exposures. Included steps are:
    ami_analyze (fringe detection)
    ami_average (average results of fringe detection)
    ami_normalize (normalize results by reference target)
    """

    spec = """
        save_averages = boolean(default=False)
    """

    # Define aliases to steps
    step_defs = {'ami_analyze': ami_analyze_step.AmiAnalyzeStep,
                 'ami_average': ami_average_step.AmiAverageStep,
                 'ami_normalize': ami_normalize_step.AmiNormalizeStep
                 }

    def process(self, input):

        log.info('Starting calwebb_ami3')

        # Load the input association table
        asn = LoadAsAssociation.load(input)

        # We assume there's one final product defined by the
        # association
        acid = asn['asn_id']
        prod = asn['products'][0]
        self.output_file = prod.get('name', self.output_file)

        # Construct lists of all the PSF and science target members
        # so that we know what we've been given to work with
        psf_files = [
            m['expname']
            for m in prod['members']
            if m['exptype'].upper() == 'PSF'
        ]
        targ_files = [
            m['expname']
            for m in prod['members']
            if m['exptype'].upper() == 'SCIENCE'
        ]

        # Make sure we found some science target members
        if len(targ_files) == 0:
            log.error('No science target members found in association table')
            log.error('Calwebb_ami3 processing will be aborted')
            return

        # If there aren't any PSF images, we can't do the normalize step
        if len(psf_files) == 0:
            log.info('No PSF reference members found in association table')
            log.info('ami_normalize step will be skipped')

        # Loop over all the images in the assocation
        psf_files = []
        targ_files = []
        for member in prod['members']:
            input_file = member['expname']

            # Do the LG analysis for this image
            log.debug('Do LG processing for member %s', input_file)
            result = self.ami_analyze(input_file)

            # Save the LG analysis results to a file
            result.meta.asn.pool_name = asn['asn_pool']
            result.meta.asn.table_name = asn.filename
            output_file = self.save_model(
                result, output_file=input_file, suffix='ami', acid=acid,
            )
            self.log.info('LG results saved to %s', output_file)

            # Save the result file name for input to ami_average
            if member['exptype'].upper() == 'PSF':
                psf_files.append(output_file)
            if member['exptype'].upper() == 'SCIENCE':
                targ_files.append(output_file)

        # Average the reference PSF image results
        psf_avg = None
        if len(psf_files) > 0:
            self.log.debug('Calling ami_average for PSF results ...')
            psf_avg = self.ami_average(psf_files)

            # Save the results to a file, if requested
            if self.save_averages:
                psf_avg.meta.asn.pool_name = asn['asn_pool']
                psf_avg.meta.asn.table_name = asn.filename

                # Perform blending of metadata for all inputs to this
                # output file
                self.log.info(
                    'Blending metadata for averaged psf...'
                )
                self.log.info(
                    "INPUT WCS: {}".format(
                        hasattr(datamodels.open(psf_files[0]), 'meta.wcs')
                    )
                )
                self.log.info("PSF_AVG type: {}".format(type(psf_avg)))
                self.log.info(
                    "PSF_AVG WCS: {}".format(
                        hasattr(psf_avg, 'meta.wcs')
                    )
                )
                blendmeta.blendmodels(psf_avg, inputs=psf_files)
                output_file = self.save_model(
                    psf_avg, suffix='psf-amiavg'
                )
                self.log.info(
                    'Averaged PSF results saved to %s',
                    output_file
                )

        # Average the science target image results
        if len(targ_files) > 0:
            self.log.debug('Calling ami_average for target results ...')
            targ_avg = self.ami_average(targ_files)

            # Save the results to a file, if requested
            if self.save_averages:
                targ_avg.meta.asn.pool_name = asn['asn_pool']
                targ_avg.meta.asn.table_name = asn.filename

                # Perform blending of metadata for all inputs to this
                # output file
                self.log.info(
                    'Blending metadata for averaged target'
                )
                blendmeta.blendmodels(targ_avg, inputs=targ_files)

                output_file = self.save_model(
                    targ_avg, suffix='amiavg'
                )
                self.log.info(
                    'Averaged target results saved to %s',
                    output_file
                )

        # Now that all LGAVG products have been produced, do
        # normalization of the target results by the reference
        # results, if reference results exist
        if psf_avg is not None:

            result = self.ami_normalize(targ_avg, psf_avg)

            # Save the result
            result.meta.asn.pool_name = asn['asn_pool']
            result.meta.asn.table_name = asn.filename

            # Perform blending of metadata for all inputs to this output file
            self.log.info(
                'Blending metadata for PSF normalized target...'
            )
            input_list = [targ_avg, psf_avg]
            blendmeta.blendmodels(result, inputs=input_list)
            output_file = self.save_model(result, suffix='aminorm')
            self.log.info(
                'Normalized result saved to %s',
                output_file
            )
            result.close()

        # We're done
        log.info('... ending calwebb_ami3')

        return
