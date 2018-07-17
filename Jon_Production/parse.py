import yaml
import sys
import os
from mson import MSONable
import numpy as np
import os.path
from utility import write_file, run_command
import numpy.random
## The form of the below code borrows from Pymatgen,  http://pymatgen.org/index.html
## and their io classes. The MSONable class is borrowed from Monty: http://guide.materialsvirtuallab.org/monty/_modules/monty/json.html

class md_config(dict,MSONable):
    """
    Creates an md_params object.

    Args:
        params (dict): A set of input parameters as a dictionary.
    """
    def __init__(self,params):
        super(md_config, self).__init__()

        if params:
            self.update(params)



class ml_config(dict,MSONable):
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
            self['unit_cell']= self['alat'] * np.array([self['lattice'][0],self['lattice'][1],self['lattice'][2]])
        if self.get('pos',False) and self.get('frac_pos',False):
            print("Warning! Positions AND fractional positions were given--"
                  "This is not intended use! You must select one or the other in your input.")
            raise Exception("Fractional position AND Cartesian positions given.")

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




class qe_config(dict,MSONable):

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

from oo_MD_Engine import setup_structure, Structure

print(setup_structure(c))
