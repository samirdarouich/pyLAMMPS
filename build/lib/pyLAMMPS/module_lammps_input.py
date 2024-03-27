import yaml
import subprocess
from typing import Any, List, Dict, Callable
from .tools import ( LAMMPS_molecules, write_lammps_ff, generate_initial_configuration, 
                     generate_input_files, generate_job_file)

## to do:
# add analysis

class LAMMPS_setup():
    """
    This class sets up structured and FAIR LAMMPS simulations. It also has the capability to build a system based on a list of molecules.
    """

    def __init__( self, system_setup: str, simulation_default: str, simulation_ensemble: str, 
                  simulation_sampling : str, submission_command: str):
        """
        Initialize a new instance of the LAMMPS_setup class.

        Parameters:
         - system_setup (str): Path to the system setup YAML file. Containing all system settings.
         - simulation_default (str): Path to the simulation default YAML file. Containing all default LAMMPS settings.
         - simulation_ensemble (str): Path to the simulation ensemble YAML file. Containing all LAMMPS ensemble settings.
         - simulation_sampling (str): Path to the sampling YAML file. Containing all sampling settings.
         - submission_command (str, optional): Command to submit jobs to cluster. Defaults to "qsub".
        
        Returns:
            None
        """

        # Open the yaml files and extract the necessary information
        with open( system_setup ) as file: 
            self.system_setup        = yaml.safe_load(file)
        
        with open( simulation_default ) as file:
            self.simulation_default  = yaml.safe_load(file)

        with open( simulation_ensemble ) as file:
            self.simulation_ensemble = yaml.safe_load(file)

        with open( simulation_sampling ) as file:
            self.simulation_sampling = yaml.safe_load(file)

        self.submission_command      = submission_command

    def prepare_simulation( self, folder_name: str, ensembles: List[str], simulation_times: List[float],
                            initial_systems: List[str]=[], copies: int=0, input_kwargs: Dict[str, Any]={}, 
                            ff_file: str="", on_cluster: bool=False, off_set: int=0, 
                            lammps_ff_callable: Callable[...,str]=None ):
        
        self.job_files = []

        # Define simulation folder
        sim_folder = f'{self.system_setup["folder"]}/{self.system_setup["name"]}/{folder_name}'

        # Write LAMMPS force field file
        if not ff_file:
            # Call the LAMMPS molecule class
            lammps_molecules = LAMMPS_molecules( mol_str = [ mol["graph"] for mol in self.system_setup["molecules"] ],
                                                force_field_path = self.system_setup["paths"]["force_field_path"] 
                                                ) 
            
            # Prepare the LAMMPS force field
            lammps_molecules.prepare_lammps_force_field()

            # Get shake dictionary
            shake_dict = lammps_molecules.get_shake_indices( self.simulation_default["shake_dict"] )

            # Get bonded styles
            style_dict = lammps_molecules.get_bonded_styles()
            
            # Write lammps ff file, either using the write_lammps_ff or any external provided function
            if lammps_ff_callable is not None and callable(lammps_ff_callable):
                print("External LAMMPS force field function is provided!\n")
                lammps_ff_file = lammps_ff_callable(  )
            else:
                lammps_ff_file = write_lammps_ff( ff_template = self.system_setup["paths"]["template"]["lammps_ff_file"], 
                                                lammps_ff_path = f"{sim_folder}/force_field.params", 
                                                potential_kwargs = { **self.simulation_default["non_bonded"]["vdw_style"], 
                                                                        **self.simulation_default["non_bonded"]["coulomb_style"] },
                                                atom_numbers_ges = lammps_molecules.atom_numbers_ges, 
                                                nonbonded = lammps_molecules.nonbonded, 
                                                bond_numbers_ges = lammps_molecules.bond_numbers_ges, 
                                                bonds = lammps_molecules.bonds,
                                                angle_numbers_ges = lammps_molecules.angle_numbers_ges, 
                                                angles = lammps_molecules.angles,
                                                torsion_numbers_ges = lammps_molecules.torsion_numbers_ges, 
                                                torsions = lammps_molecules.torsions,
                                                only_self_interactions = self.simulation_default["non_bonded"]["lammps_mixing"], 
                                                mixing_rule = self.simulation_default["non_bonded"]["mixing"],
                                                ff_kwargs = self.simulation_default["non_bonded"]
                                                )
        else:
            lammps_ff_file = ff_file
        
        for i, (temperature, pressure, density) in enumerate( zip( self.system_setup["temperature"], 
                                                                   self.system_setup["pressure"], 
                                                                   self.system_setup["density"] ) ):
            
            job_files = []
            # Define folder for specific temp and pressure state
            state_folder = f"{sim_folder}/temp_{temperature:.0f}_pres_{pressure:.0f}"

            # Build system with PLAYMOL and write LAMMPS data if no initial system is provided
            if not initial_systems:
                
                lammps_data_file = generate_initial_configuration( lammps_molecules = lammps_molecules,
                                                                   destination_folder = state_folder,
                                                                   molecules_dict_list = self.system_setup["molecules"],
                                                                   density = density,
                                                                   template_xyz = self.system_setup["paths"]["template"]["xyz_file"],
                                                                   playmol_ff_template = self.system_setup["paths"]["template"]["playmol_ff_file"],
                                                                   playmol_input_template = self.system_setup["paths"]["template"]["playmol_input_file"],
                                                                   playmol_bash_file = self.system_setup["paths"]["template"]["playmol_bash_file"],
                                                                   lammps_data_template = self.system_setup["paths"]["template"]["lammps_data_file"],
                                                                   submission_command = self.submission_command, 
                                                                   on_cluster = on_cluster
                                                                )
            
                flag_restart = False
            else:
                lammps_data_file = initial_systems[i]
                print(f"\nIntial system provided for at: {lammps_data_file}\n")
                flag_restart = ".restart" in lammps_data_file
                if flag_restart: 
                    print("Restart file is provided. Continue simulation from there!\n")

            # Define folder for each copy
            for copy in range( copies + 1 ):
                copy_folder = f"{state_folder}/copy_{copy}"

                # Produce input files (for each ensemble an own folder 0x_ensemble)
                input_files = generate_input_files( destination_folder = copy_folder, 
                                                    input_template = self.system_setup["paths"]["template"]["lammps_input_file"],
                                                    ensembles = ensembles, 
                                                    temperature = temperature, 
                                                    pressure = pressure,
                                                    data_file = lammps_data_file, 
                                                    ff_file = lammps_ff_file,
                                                    simulation_times = simulation_times,
                                                    dt = self.simulation_default["system"]["dt"], 
                                                    kwargs = { **self.simulation_default,
                                                               **self.simulation_sampling, 
                                                               **input_kwargs,
                                                               "style": style_dict,
                                                               "shake_dict": shake_dict, 
                                                               "restart_flag": flag_restart }, 
                                                    ensemble_definition = self.simulation_ensemble,
                                                    off_set = off_set
                                                    )
                
                # Create job file
                job_files.append( generate_job_file( destination_folder = copy_folder, 
                                                     job_template = self.system_setup["paths"]["template"]["job_file"], 
                                                     input_files = input_files, 
                                                     ensembles = ensembles,
                                                     job_name = f'{self.system_setup["name"]}_{temperature:.0f}_{pressure:.0f}',
                                                     job_out = f"job_{temperature:.0f}_{pressure:.0f}.sh", 
                                                     off_set = off_set 
                                                    ) 
                                )
                
            self.job_files.append( job_files )


    def submit_simulation(self):
        """
        Function that submits predefined jobs to the cluster.
        
        Parameters:
            None

        Returns:
            None
        """
        for temperature, pressure, job_files in zip( self.system_setup["temperature"], self.system_setup["pressure"], self.job_files ):
            print(f"\nSubmitting simulations at Temperature = {temperature:.0f} K, Pressure = {pressure:.0f} bar\n")

            for job_file in job_files:
                print(f"Submitting job: {job_file}")
                subprocess.run( [self.submission_command, job_file] )
                print("\n")