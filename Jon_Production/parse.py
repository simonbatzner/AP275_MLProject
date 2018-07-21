import yaml
import sys
import os
import numpy as np
import os.path
from utility import write_file, run_command
import numpy.random


class md_config(dict):
    """
    Creates an md_params object.

    Args:
        params (dict): A set of input parameters as a dictionary.
    """
    def __init__(self,params):
        super(md_config, self).__init__()

        if params:
            self.update(params)



class ml_config(dict):
    """
    Creates an ml_params object. Will probably be replaced
    as soon as we coordinate with Simon.

    Args:
        params (dict): A set of input parameters as a dictionary.
    """
    def __init__(self,params):

        super(ml_config, self).__init__()
        if params:
            self.update(params)


class structure_config(dict):

    def __init__(self,params,warn=True):


        self._params=['lattice','alat','position','frac_pos','pos','fractional',
                      'unit_cell','pert_size','elements']
        self['lattice'] = None

        if params:
            self.update(params)
        #super(structure_config, self).__init__()

        self['elements']  = []
        self.positions = []

        check_list = {'alat': self.get('alat', False),
            'position':self.get('frac_pos', False) or self.get('pos',False),
            'lattice':self.get('lattice', False)}
        if warn and not all(check_list.values()):
            print('WARNING! Some critical parameters which are needed for structures'
                  ' to work are not present!!')
            for x in check_list.keys():
                if not check_list[x]: print("Missing",x)
            raise Exception("Malformed input file-- structure parameters incorrect.")

        if self['lattice']:
            self['lattice'] =np.array(self['lattice'])
            self['unit_cell']= self['alat'] * np.array([self['lattice'][0],self['lattice'][1],self['lattice'][2]])
        if self.get('pos',False) and self.get('frac_pos',False):
            print("Warning! Positions AND fractional positions were given--"
                  "This is not intended use! You must select one or the other in your input.")
            raise Exception("Fractional position AND Cartesian positions given.")


        if self['lattice'].shape!=(3,3):
            print("WARNING! Inappropriately shaped cell passed as input to structure!")
            raise Exception('Lattice has shape', np.shape(self['lattice']))

        if self.get('pos',False):
            self.fractional=False
            self.positions = self['pos']
        else:
            self.fractional=True
            self.positions = self['frac_pos']

        for atom in self.positions:
            self['elements'].append(atom[0])

        if self.get('pert_size'):
            for atom in self.positions:
                for pos in atom[1]:
                    pos+= numpy.random.normal(0,scale=self['pert_size'])

        super(structure_config,self).__init__(self)


def load_config(path,verbose=True):

    if not os.path.isfile(path) and verbose:
        raise OSError('Configuration file does not exist.')

    with open(path, 'r') as stream:
        try:
            out = yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            print(exc)

    return out

def setup_configs(path,verbose=True):

    setup_dict = load_config(path, verbose=verbose)


    if 'md_params' in setup_dict.keys():
        md= md_params.from_dict(setup_dict['md_params'])
    else:
        md = md_params.from_dict({})

    if  'qe_params' in setup_dict.keys():
        qe = qe_config.from_dict(setup_dict['qe_params'])
    else:
        qe = qe_config.from_dict({})

    if 'structure_params' in setup_dict.keys():
        structure = structure_config(setup_dict['structure_params'])
    else:
        structure = structure_config({})

    if 'ml_params' in setup_dict.keys():
        ml = ml_config(setup_dict['ml_params'])
        if ml_config['regression_model']=='GP':
            pass
            #ml= GaussianProcess() #TODO: integrate this with Simon's new classes
    else:
        ml = ml_config({})





class Atom():
    def __init__(self, position=(0., 0., 0.), velocity=(0., 0., 0.), force=(0., 0., 0.), initial_pos=(0, 0, 0),
                 mass=None, element='', constraint=(False, False, False)):

        self.position = np.array(position)
        self.velocity = np.array(velocity)
        self.force = np.array(force)
        self.element = str(element)
        self.trajectory = []

        # Used in Verlet integration
        self.prev_pos = np.array(self.position)
        self.initial_pos = self.position if self.position.all != (0, 0, 0) else initial_pos
        # Boolean which signals if the coordinates are fractional in their original cell
        self.constraint = list(constraint)
        self.fingerprint = rand.rand()  # This is how I tell atoms apart. Easier than indexing them manually...

        self.mass = mass or 1.0

        self.parameters = {'position': self.position,
                           'velocity': self.velocity,
                           'force': self.force,
                           'mass': self.mass,
                           'element': self.element,
                           'constraint': self.constraint,
                           'initial_pos': self.initial_pos}
    # Pint the
    def __str__(self):
        return str(self.parameters)

    def get_position(self):
        return self.position

    def get_velocity(self):
        return self.velocity

    def get_force(self):
        return self.force

    def apply_constraint(self):
        for n in range(3):
            if self.constraint[n]:
                self.velocity[n] = 0.
                self.force[n] = 0.


class Structure(list):
    """
    Class which stores list of atoms as well as information on the structure,
    which is acted upon by the MD engine.
    Parameterized by the structure_params object in the YAML input files.

    args:
    alat (float): Scaling factor for the lattice
    cell (3x3 nparray): Matrix of vectors which define the unit cell
    elements (list [str]): Names of elements in the system
    atom_list (list [Atom]): Atom objects which are propagated by the MD Engine
    """
    mass_dict = {'H': 1.0, "Al": 26.981539, "Si": 28.0855}

    def __init__(self, alat=1.,lattice=np.eye(3), atoms=None,fractional=True):


        self.atoms = [] or atoms
        self.elements = [at.element for at in atoms]
        self.species =  [] or set(self.elements)
        self.alat = alat
        self.lattice = lattice
        self.fractional = fractional

        super(Structure, self).__init__(self.atoms)


    def print_atoms(self,fractional=True):

        fractional = self.fractional

        if fractional:
            for n, at in enumerate(self.atoms):
                print("{}:{} ({},{},{}) ".format(n, at.element, at.position[0], at.position[1], at.position[2]))
        else:
            for n, at in enumerate(self.atoms):
                print("{}:{} ({},{},{}) ".format(n, at.element, at.position[0], at.position[1], at.position[2]))

    def __str__(self):
        self.print_atoms()

    def get_positions(self):
        return [atom.position for atom in self.atoms]

    def get_positions_and_element(self):
        return[[atom.element,atom.position] for atom in self.atoms]

    def set_forces(self,forces):
        """
        Sets forces
        :param forces: List of length of atoms in system of length-3 force components
        :return:
        """
        if len(self.atoms)!=len(forces):
            print("Warning! Length of list of forces to be set disagrees with number of atoms in the system!")
            Exception('Forces:',len(forces),'Atoms:',len(self.atoms))
        for n,at in enumerate(self.atoms):
            at.force = forces[n]

    def print_structure(self):
        lattice = self.lattice
        print('Alat:{}'.format(self.alat))
        print("Cell:\t [[ {}, {}, {}".format(lattice[0,0],lattice[0,1],lattice[0,2]))
        print(" \t [ {},{},{}]".format(lattice[1,0],lattice[1,1],lattice[1,2]))
        print(" \t [ {},{},{}]]".format(lattice[2,0],lattice[2,1],lattice[2,2]))





def setup_structure(structure_config):

    sc = structure_config

    if sc['velocities']: has_vel = True
    if sc['']



    return Structure(alat=sc['alat'], lattice = sc['lattice'],elements=sc['elements'],)


class qe_config(dict):

    """
    Contains parameters which configure Quantum ESPRESSO pwscf runs,
    as well as the methods to implement them.
    """
    def __init__(self, params={},warn=False):

        super(qe_config, self).__init__()
        if params:
            self.update(params)
        qe = self
        if not(qe.get('system_name',False)): self['system_name'] = 'QE'
        if not(qe.get('pw_command',False)): self['pw_command'] = os.environ.get('PWSCF_COMMAND')
        if not(qe.get('parallelization',False)): self['parallelization'] = {'np':1,'nk':0,'nt':0,'nd':0,'ni':0}

        if warn and not all([
            qe.get('ecut', False),
            qe.get('nk', False),
            qe.get('sc_dim', False),
            qe.get('pw_command', False),
            qe.get('pseudo_dir', False),
            qe.get('in_file', False)]):
            print('WARNING! Some critical parameters which are needed for QE to work are not present!')

    def as_dict(self):
        d = dict(self)
        d["@module"] = self.__class__.__module__
        d["@class"] = self.__class__.__name__
        return d

    #@classmethod
    #def from_dict(cls, d):
    #    return qe_config({k: v for k, v in d.items() if k not in ("@module",
    #                                                          "@class")})

    def get_correction_number(self):
        folders_in_correction_folder = list(os.walk(self.correction_folder))[0][1]

        steps = [fold for fold in folders_in_correction_folder if self.system_name + "_step_" in fold]

        if len(steps) >= 1:
            stepvals = [int(fold.split('_')[-1]) for fold in steps]
            correction_number = max(stepvals)
        else:
            return 0
        return correction_number + 1

    def run_espresso(self, atoms, cell, iscorrection = False):

        pseudopots = {}
        elements = [atom.element for atom in atoms]
        for element in elements:
            pseudopots[element] = self.pseudopotentials[element]

        ase_struc = Atoms(symbols=[atom.element for atom in atoms],
                          positions=[atom.position for atom in atoms],
                          cell=cell,
                          pbc=[0, 0, 0] if self.molecule else [1, 1, 1])

        struc = Struc(ase2struc(ase_struc))

        if self.molecule:
            kpts = Kpoints(gridsize=[1, 1, 1], option='gamma', offset=False)
        else:
            nk = self.nk
            kpts = Kpoints(gridsize=[nk, nk, nk], option='automatic', offset=False)

        if iscorrection:
            self.correction_number = self.get_correction_number()
            # print("rolling with correction number",qe_config.correction_number)
            dirname = self.system_name + '_step_' + str(self.correction_number)
        else:
            dirname = 'temprun'
        runpath = Dir(path=os.path.join(os.environ['PROJDIR'], "AIMD", dirname))
        input_params = PWscf_inparam({
            'CONTROL': {
                'prefix': self.system_name,
                'calculation': 'scf',
                'pseudo_dir': os.environ['ESPRESSO_PSEUDO'],
                'outdir': runpath.path,
                #            'wfcdir': runpath.path,
                'disk_io': 'low',
                'tprnfor': True,
                'wf_collect': False
            },
            'SYSTEM': {
                'ecutwfc': self.ecut,
                'ecutrho': self.ecut * 8,
                #           'nspin': 4 if 'rel' in potname else 1,

                'occupations': 'smearing',
                'smearing': 'mp',
                'degauss': 0.02,
                # 'noinv': False
                # 'lspinorb':True if 'rel' in potname else False,
            },
            'ELECTRONS': {
                'diagonalization': 'david',
                'mixing_beta': 0.5,
                'conv_thr': 1e-7
            },
            'IONS': {},
            'CELL': {},
        })

        output_file = run_qe_pwscf(runpath=runpath, struc=struc, pseudopots=pseudopots,
                                   params=input_params, kpoints=kpts,
                                   parallelization=self.parallelization)
        output = parse_qe_pwscf_output(outfile=output_file)

        with open(runpath.path + '/en', 'w') as f:
            f.write(str(output['energy']))
        with open(runpath.path + '/pos', 'w')as f:
            for pos in [atom.position for atom in atoms]:
                f.write(str(pos) + '\n')

        return output

    def create_scf_input(self):
        """
        Jon V's version of the PWSCF formatter.
        Works entirely based on internal settings.
        """

        scf_text = """ &control
            calculation = 'scf'
            pseudo_dir = '{0}'
            outdir = '{1}'
            tprnfor = .true.
         /
         &system
            ibrav= 0
            nat= {2}
            ntyp= 1
            ecutwfc ={3}
            nosym = .true.
         /
         &electrons
            conv_thr =  1.0d-10
            mixing_beta = 0.7
         /
        ATOMIC_SPECIES
         Si  28.086  Si.pz-vbc.UPF
        {4}
        {5}
        K_POINTS automatic
         {6} {6} {6}  0 0 0
            """.format(self['pseudo_dir'], self['outdir'], \
                       self['nat'], self['ecut'], self['cell'], self['pos'], self['nk'])
        return scf_text

    def run_scf_from_text(self,scf_text, npool, out_file='pw.out', in_file='pw.in'):

        # write input file
        write_file(in_file, scf_text)

        # call qe
        qe_command = 'mpirun {0} -npool {1} < {2} > {3}'.format(self['pw_loc'], npool, in_file, out_file)
        run_command(qe_command)


a = load_config('input.yaml')
#print(a['qe_params'])
b=qe_config(a['qe_params'],warn=True)
#print(b)

print(a['structure_params'])
c= structure_config(a['structure_params'])
print(c)
#print(c.as_dict())

