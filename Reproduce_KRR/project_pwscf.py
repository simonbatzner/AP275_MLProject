import os
from objects import *
import numpy


class PWscf_inparam(Param):
	"""
	Data class containing parameters for a Quantum Espresso PWSCF calculation
	it does not include info on the cell itself, since that will be taken from a Struc object
	"""
	pass


def qe_value_map(value):
	"""
	Function used to interpret correctly values for different
	fields in a Quantum Espresso input file (i.e., if the user
	specifies the string '1.0d-4', the quotes must be removed
	when we write it to the actual input file)
	:param: a string
	:return: formatted string to be used in QE input file
	"""
	if isinstance(value, bool):
		if value:
			return '.true.'
		else:
			return '.false.'
	elif isinstance(value, (float, numpy.float)) or isinstance(value, (int, numpy.int)):
		return str(value)
	elif isinstance(value, str):
		return "'{}'".format(value)
	else:
		print("Strange value ", value)
		raise ValueError


def write_pwscf_input(runpath, params, struc, kpoints, pseudopots, constraint=None):
	"""Make input param string for PW"""
	# automatically fill in missing values
	pcont = params.content
	pcont['SYSTEM']['ntyp'] = struc.n_species
	pcont['SYSTEM']['nat'] = struc.n_atoms
	pcont['SYSTEM']['ibrav'] = 0
	# Write the main input block
	inptxt = ''
	for namelist in ['CONTROL', 'SYSTEM', 'ELECTRONS', 'IONS', 'CELL']:
		inptxt += '&{}\n'.format(namelist)
		for key, value in pcont[namelist].items():
			inptxt += '	{} = {}\n'.format(key, qe_value_map(value))
		inptxt += '/ \n'
	# write the K_POINTS block
	if kpoints.content['option'] == 'automatic':
		inptxt += 'K_POINTS {automatic}\n'
	
	
	if kpoints.content['option'] == 'gamma':
		inptxt +="K_POINTS {gamma}\n"

	else:			
		inptxt += ' {:d} {:d} {:d}'.format(*kpoints.content['gridsize'])
	
	
		if kpoints.content['offset']:
			inptxt += '  1 1 1\n'
		else:
			inptxt += '  0 0 0\n'

	# write the ATOMIC_SPECIES block
	inptxt += 'ATOMIC_SPECIES\n'
	for elem, spec in struc.species.items():
		inptxt += '  {} {} {}\n'.format(elem, spec['mass'], pseudopots[elem].content['name'])

	# Write the CELL_PARAMETERS block
	inptxt += 'CELL_PARAMETERS {angstrom}\n'
	for vector in struc.content['cell']:
		inptxt += ' {} {} {}\n'.format(*vector)

	# Write the ATOMIC_POSITIONS in crystal coords
	inptxt += 'ATOMIC_POSITIONS {angstrom}\n'
	for index, positions in enumerate(struc.content['positions']):
		inptxt += '  {} {:1.5f} {:1.5f} {:1.5f}'.format(positions[0], *positions[1])
		if constraint and constraint.content['atoms'] and str(index) in constraint.content['atoms']:
			inptxt += ' {} {} {} \n'.format(*constraint.content['atoms'][str(index)])
		else:
			inptxt += '\n'

	infile = TextFile(path=os.path.join(runpath.path, 'pwscf.in'), text=inptxt)
	infile.write()
	return infile


def run_qe_pwscf(struc, runpath, pseudopots, params, kpoints, constraint=None, ncpu=1):
	pwscf_code = ExternalCode({'path': os.environ['PWSCF_COMMAND']})
	prepare_dir(runpath.path)
	infile = write_pwscf_input(params=params, struc=struc, kpoints=kpoints, runpath=runpath,
							   pseudopots=pseudopots, constraint=constraint)
	outfile = File({'path': os.path.join(runpath.path, 'pwscf.out')})
	pwscf_command = "mpirun -np {} {} < {} > {}".format(ncpu, pwscf_code.path, infile.path, outfile.path)
	run_command(pwscf_command)
	return outfile


def parse_qe_pwscf_output(outfile):

	forces=[]
	positions=[]
	total_force = None
	pressure = None
	
	#Flags to start collecting final coordinates
	final_coords=False
	get_coords=False
	
	with open(outfile.path, 'r') as outf:
		for line in outf:
			if line.lower().startswith('     pwscf'):
				walltime = line.split()[-3] + line.split()[-2]
			
			if line.lower().startswith('     total force'):
				total_force = float(line.split()[3]) * (13.605698066 / 0.529177249)
			
			if line.lower().startswith('!    total energy'):
				total_energy = float(line.split()[-2]) * 13.605698066
				
			if line.lower().startswith('          total   stress'):
				pressure = float(line.split('=')[-1])
			
			if line.lower().startswith('     number of k points='):
				kpoints  = float(line.split('=')[-1])

			if line.lower().startswith('     unit-cell volume'):
				line=line.split('=')[-1]
				line=line.split('(')[0]
				line=line.strip()
				volume   = float(line)


				
			## Chunk of code meant to get the final coordinates of the atomic positions
			if line.lower().startswith('begin final coordinates'):
				final_coords=True
				continue
			if line.lower().startswith('atomic_positions') and final_coords==True:
				continue
			if line.lower().startswith('end final coordinates'):
				final_coords=False
			if final_coords==True and line.split()!=[]:
				positions.append( [ line.split()[0], [float(line.split()[1]),
						      float(line.split()[2]),float(line.split()[3])  ] ] )
				
				
			if line.find('force')!=-1 and line.find('atom')!=-1:
				line=line.split('force =')[-1]
				line=line.strip()
				line=line.split(' ')
				#print("Parsed line",line,"\n") 
				line=[x for x in line if x!='']
				temp_forces=[]
				for x in line:
					temp_forces.append(float(x))
				forces.append(list(temp_forces))
				
				
				

	result = {'energy': total_energy, 'kpoints':kpoints, 'volume': volume, 'positions':positions}
	if forces!=[]:
		result['forces'] = forces
	if total_force!=None:
		result['total_force'] = total_force
	if pressure!=None:
		result['pressure'] = pressure
	return result


##################### NEW BELOW
	

class PW_PP_inparam(Param):
	"""
	Data class containing parameters for a Quantum Espresso PWSCF post-processing calculation.
	"""
	pass


# THIS IS UNFINISHED
def run_qe_pp( runpath,  params,plot_vecs,   ncpu=1):
	pp_code = ExternalCode({'path': os.environ['PP_COMMAND']})
	prepare_dir(runpath.path)
	infile = write_pp_input(params=params, plot_vecs=plot_vecs)
	outfile = File({'path': os.path.join(runpath.path, 'pwscf.out')})
	pp_command = "mpirun -np {} {} < {} > {}".format(ncpu, pp_code.path, infile.path, outfile.path)
	run_command(pwscf_command)
	return outfile



#TODO: MAKE THIS CONNECT TO PWSCF RUN OBJECTS.
# THIS IS ALSO UNFINISHED
def write_pp_input(runpath, params, kpoints, pseudopots, constraint=None):
	"""Make input param string for PW"""
	# automatically fill in missing values
	pcont = params.content
	# Write the main input block
	inptxt = ''
	for namelist in ['inputpp', 'plot']:
		inptxt += '&{}\n'.format(namelist)
		for key, value in pcont[namelist].items():
			inptxt += '	{} = {}\n'.format(key, qe_value_map(value))
		inptxt += '/ \n'

	infile = TextFile(path=os.path.join(runpath.path, 'pwscf.in'), text=inptxt)
	infile.write()
	return infile