#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# pylint: disable=line-too-long, invalid-name, too-many-arguments

""""
Steven Torrisi
"""
import time as ti
import pprint

import numpy as np
import numpy.linalg as la

from parse import load_config_yaml, QE_Config, Structure_Config, ml_config, MD_Config
from utility import first_derivative_2nd, first_derivative_4th
from regression import GaussianProcess

mass_dict = {'H': 1.0, "Al": 26.981539, "Si": 28.0855, 'O': 15.9994}


class MD_Engine(MD_Config):
    def __init__(self, structure, md_config, qe_config, ml_config, hpc_config=None):
        """
        Engine which drives accelerated molecular dynamics. Is of type MD_Config
        so that molecular dynamics options are referred to using self.attributes.

        Args:
            structure   (Structure): Contains all information about atoms in cell.
            md_config   (MD_Config): Parameters for molecular dynamics simulation
            qe_config   (QE_Config): Parameters for quantum ESPRESSO runs
            ml_model    (RegressionModel): Regression model which provides forces or energies

        """

        # Set configurations
        super(MD_Engine, self).__init__(md_config)

        self.structure = structure
        self.qe_config = qe_config
        self.ml_config = ml_config
        self.hpc_config = hpc_config

        # init regression model
        # TODO make sure params for both sklearn and self-made are all there and not redudant

        self.ml_model = GaussianProcess(training_dir=ml_config['training_dir'],
                                        length_scale=ml_config['gp_params']['length_scale'],
                                        length_scale_min=ml_config['gp_params']['length_scale_min'],
                                        length_scale_max=ml_config['gp_params']['length_scale_max'],
                                        force_conv=ml_config['gp_params']['threshold_params']['force_conv'],
                                        thresh_perc=ml_config['gp_params']['threshold_params']['thresh_perc'],
                                        eta_lower=ml_config['fingerprint_params']['eta_lower'],
                                        eta_upper=ml_config['fingerprint_params']['eta_upper'],
                                        eta_length=ml_config['fingerprint_params']['eta_length'],
                                        cutoff=ml_config['fingerprint_params']['cutoff'],
                                        sklearn=ml_config['sklearn'])

        # init training database for regression model
        if ml_config['training_dir'] is not None:
            self.ml_model.init_database(structure=self.structure)

        # Contains info on each frame according to wallclock time and configuration
        self.system_trajectory = []
        self.augmentation_steps = []

        # MD frame cnt, corresponds to DFT data in correction folder
        self.frame_cnt = 0

    # noinspection PyPep8Naming
    def get_energy(self):
        """
        If ML: use regression model to get energy
        If AIMD: call ESPRESSO and report energy
        If LJ: compute the Lennard-Jones energy of the configuration

        :return: float, energy of configuration
        """

        if self['mode'] == 'ML':
            return self.ml_model.get_energy(self.structure)

        if self['mode'] == 'AIMD':
            result = self.qe_config.run_espresso()
            return result['energy']

        if self['mode'] == 'LJ':

            eps = self['LJ_eps']
            rm = self['LJ_rm']
            E = 0.
            for at in self.structure:
                for at2 in self.structure:
                    if at.fingerprint != at2.fingerprint:
                        disp = la.norm(at.position - at2.position)
                        if self['verbosity'] >= 4:
                            print('Current LJ disp between atoms is:', disp)
                        if self['verbosity'] == 5:
                            print("LJ Energy of the pair is ", .5 * eps * ((rm / disp) ** 12 - 2 * (rm / disp) ** 6))
                        E += .5 * eps * ((rm / disp) ** 12 - 2 * (rm / disp) ** 6)
            return E

    def set_forces(self):
        """
        If ML, use regression model to get forces
        If AIMD, call ESPRESSO and report forces
        If LJ, compute the Lennard-Jones forces of the configuration by finite differences.
        """

        # run espresso
        if self['mode'] == 'AIMD':

            results = self.qe_config.run_espresso(self.structure, cnt=self.frame_cnt)

            if self.verbosity == 4:
                print("E0:", results['energy'])

            for n, at in enumerate(self.structure):
                at.force = list(np.array(results['forces'][n]) * 13.6 / 0.529177)

            return

        # compute Lennard Jones
        elif self.mode == 'LJ':

            self.set_fd_forces()
            pass

        # run regression model
        elif self.md_config['mode'] == 'ML':

            if self.ml_model.type == 'energy':
                self.ml_model.predict(structure=self.structure, target='e')

            elif self.ml_model.type == 'force':
                forces = self.ml_model.predict(structure=self.structure, target='f')

                for n, at in enumerate(self.structure):
                    at.force = list(np.array(forces[n]) * 13.6 / 0.529177)

                return

    def set_fd_forces(self):
        """
        Perturbs the atoms by a small amount dx in each direction and returns the gradient (and thus the force)
        via a finite-difference approximation.
        """

        dx = self.fd_dx
        fd_accuracy = self['fd_accuracy']

        if self.energy_or_force_driven == "energy" and self.md_config.mode == "AIMD":
            print("WARNING! You are asking for an energy driven model with Ab-Initio MD;",
                  " AIMD is configured only to work on a force-driven basis.")

        E0 = self.get_energy()
        if self.verbosity == 4:
            print('E0:', E0)

        # set forces
        for atom in self.structure:
            for coord in range(3):

                # Perturb to x + dx
                atom.position[coord] += dx
                Eplus = self.get_energy()

                # Perturb to x - dx
                atom.position[coord] -= 2 * dx
                Eminus = self.get_energy()

                if fd_accuracy == 4:
                    # Perturb to x + 2dx
                    atom.position[coord] += 3 * dx
                    Epp = self.get_energy()

                    # Perturb to x - 2dx
                    atom.position[coord] -= 4 * dx
                    Emm = self.get_energy()

                    # Perturb to x - dx
                    atom.position[coord] += dx

                # Return atom to initial position
                atom.position[coord] += dx

                if fd_accuracy == 2:
                    atom.force[coord] = -first_derivative_2nd(Eminus, Eplus, dx)
                elif fd_accuracy == 4:
                    atom.force[coord] = -first_derivative_4th(Emm, Eminus, Eplus, Epp, dx)
                if self.verbosity == 5:
                    print("Just assigned force on atom's coordinate", coord, " to be ",
                          -first_derivative_2nd(Eminus, Eplus, dx))

        for at in self.structure:
            at.apply_constraint()

    def take_timestep(self, dt=None, method=None):
        """
        Propagate forward in time by dt using specified method, then update forces.

        Args:
            dt (float)  : Defaults to specified in input, timestep duration
            method (str): Choose one of Verlet or Third-Order Euler.
        """
        tick = ti.time()
        if self['verbosity'] >= 3:
            print(self.get_report(forces=True))

        # TODO: Make sure that this works when dt is negative,
        # rewind function will do this nicely
        dt = dt or self.dt
        dtdt = dt * dt

        method = method or self["timestep_method"]

        # third-order euler method, a suggested way to begin a Verlet run
        # see: https://en.wikipedia.org/wiki/Verlet_integration#Starting_the_iteration

        if method == 'TO_Euler':
            for atom in self.structure:
                for i in range(3):
                    atom.prev_pos[i] = np.copy(atom.position[i])
                    atom.position[i] += atom.velocity[i] * dt + atom.force[i] * dtdt * .5 / atom.mass
                    atom.velocity[i] += atom.force[i] * dt / atom.mass

        # superior Verlet integration
        # see: https://en.wikipedia.org/wiki/Verlet_integration

        # Todo vectorize this

        elif method == 'Verlet':
            for atom in self.structure:
                for i in range(3):
                    # Store the current position to later store as the previous position
                    # After using it to update the position

                    temp_coord = np.copy(atom.position[i])
                    atom.position[i] = 2 * atom.position[i] - atom.prev_pos[i] + \
                                       atom.force[i] * dtdt * .5 / atom.mass
                    atom.velocity[i] += atom.force[i] * dt / atom.mass
                    atom.prev_pos[i] = np.copy(temp_coord)
                    if self.verbosity == 5: print("Just propagated a distance of ",
                                                  atom.position[i] - atom.prev_pos[i])

        if self['assert_boundaries']:
            self.assert_boundary_conditions()

        self.time += dt
        self.frame += 1
        self.set_forces()

        tock = ti.time()

        self.structure.record_trajectory(frame=self.frame, time=self.dt, position=True, elapsed=tock - tick)

    # TODO Determine all of the necessary ingredients which may or may not be missing
    # TODO Info redundant or common to both should be checked here as well
    def setup_run(self):

        """
        Checks a few classes within the 5 parameters before run begins.
        Additionally opens output file in an output file was specified.

        This is where handling of the augmentation database will occur.
        """
        self.qe_config.validate_against_structure(self.structure)

        # --------------------------------------------------
        # Check consistency of correction folders
        # --------------------------------------------------
        qe_corr = False
        ml_corr = False

        if self.mode == 'ML':

            if self.qe_config.get('correction_folder', False):
                qe_corr = True
            if self.ml_model.correction_folder:
                ml_corr = True

            # @STEVEN: we shouldn't pass this separately -- include one in the input and init both configs from that dir
            if ml_corr and qe_corr:
                if self.qe_config['correction_folder'] != self.ml_model.correction_folder:
                    print("WARNING!!! Correction folder is inconsistent between the QE config and the ML config!"
                          "This is very bad-- the ML model will not get any better and this will result in a loop")
                    raise Exception("Mismatch between qe config correction folder and ML config.")

            if ml_corr and not qe_corr:
                self.qe_config['correction_folder'] = self.ml_model.correction_folder

            if qe_corr and not ml_corr:
                self.ml_model.correction_folder = self.qe_config['correction_folder']

        # ----------------------------------------------------------------------------------------
        # check to see if training database of DFT forces exists, else: run DFT and bootstrap
        # -----------------------------------------------------------------------------------------

        if self.mode == "ML" and self.ml_model.training_data is not None:
            self.frame_cnt = 0

            # @STEVEN: we discussed to make run_espresso part of the engine, what is the status on that?
            self.qe_config.run_espresso(self.structure, cnt=0, augment_db=True)
            self.ml_model.retrain()

    def run(self, first_euler=True):
        """
        Compute forces, move timestep
        """
        # --------------
        #   First step
        # --------------

        self.set_forces()

        if self.frame == 0:
            self.ml_model.set_error_threshold()

        self.structure.record_trajectory(self.frame, self.time, position=True, force=True)

        if self['time'] == 0 and first_euler:
            self.take_timestep(method='TO_Euler')

        # ------------------------
        #  Primary iteration loop
        # ------------------------
        while self.time < self.get('tf', np.inf) and self['frame'] < self.get('frames', np.inf):

            self.take_timestep(method=self['timestep_method'])

            if self.mode == 'ML':

                if self.ml_model.gauge_uncertainty():
                    continue

                # if not, compute DFT, retrain model, move on
                else:
                    if self.verbosity == 2: print(
                        "Timestep with unacceptable uncertainty detected! \n Rewinding one step, and calling espresso to re-train the model.")
                    self.qe_config.run_espresso(self.structure, self.cell, cnt=self.frame_cnt,
                                                iscorrection=True)
                    self.ml_model.retrain(self.structure)
                    self.take_timestep(dt=-self['dt'])

        self.conclude_run()

    # TODO: Implement end-run report
    def conclude_run(self):
        print("===============================================================\n")
        print("Run concluded. Final positions and energy of configuration:\n")
        print("Energy:", self.get_energy(), '\n')
        print(self.get_report(forces=True))

    def get_report(self, forces=True, velocities=False, time_elapsed=0):
        """
        Prints out the current statistics of the atoms line by line.

        Args:

            :param forces:      (bool) Determines if forces will be printed.
            :param velocities:  (bool) Determines if velocities will be printed.
            :param time_elapsed: (float) Puts elapsed time for a frame into the report
        """
        report = 'Frame#:{},SystemTime:{},ElapsedTime{}:\n'.format(self['frame'], np.round(self['time'], 3),
                                                                   np.round(time_elapsed, 3))
        report += 'Atom,Element,Position'
        report += ',Force' if forces else ''
        report += ',Velocity' if velocities else ''
        report += '\n'
        for n, at in enumerate(self.structure):
            report += '{},{},{}{}{} \n'.format(n, at.element, str(tuple([np.round(x, 4) for x in at.position])),
                                               ',' + str(
                                                   tuple([np.round(v, 4) for v in at.velocity])) if velocities else '',
                                               ',' + str(tuple([np.round(f, 4) for f in at.force])) if forces else '')

        return report


def main():
    # setup
    config = load_config_yaml('H2_test.yaml')

    qe_config = QE_Config(config['qe_params'], warn=True)
    # pprint.pprint(qe_config)

    structure = Structure_Config(config['structure_params']).to_structure()
    # qe_config.run_espresso(struc_config, augment_db=True)

    ml_config_ = ml_config(params=config['ml_params'], print_warn=True)
    # pprint.pprint(ml_config_)

    md_config = MD_Config(params=config['md_params'], warn=True)
    # # pprint.pprint(md_config)

    engine = MD_Engine(structure, md_config, qe_config, ml_config_)
    # print(engine)

    engine.run()


if __name__ == '__main__':
    main()
