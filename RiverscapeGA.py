import sys
import os
import itertools
import math
import random
import getopt
import scipy as sp
import numpy as np
import pandas as pd
import networkx as nx
import multiprocessing as mp
from functools import partial
from collections import OrderedDict
from sortedcontainers import SortedDict

#julia
from julia.api import Julia
from julia import Base, Main
from julia.Main import println, redirect_stdout

import timeit

#genetic algorithms
from deap import base, creator, tools, algorithms

#autoStreamTree packages
from riverscape.acg_menu import parseArgs
import riverscape.circuitscape_runner as cs
import riverscape.transform as trans


"""
Parallelization notes -- failed attempts.
What I've tried:
	1) Multiprocessing.pool with deap
		Observation: Runtimes longer with more processors
		Problems: I think there are multiple:
			- The Julia interface may still be running them 
				serially
			- The overhead of sending around all of the global
				variables might be too high to see any positive 
				change with the small tests I've been doing
		Verdict: Revisit this option later. Need to get everything up 
			and runnign first
	2) Native parallelization of pairwise comparisons in Circuitscape
			Observation: Takes LONGER per run !??
			Problems: I think these individual runs are so short that the overhead
				of sending data within Julia/CS outweighs the benefits
			Verdict: Probably not going to be a good solution.
	3) *Meta-parallelization of ini files in Julia
			Observation: Runtimes longer with more processors
			Problems: May be just that my laptop is bogged down
			Verdict: Try messing with this again later. This only parallelizes
				the Circuitscape part, but that's better than nothing...
	
	Things to try: 
		- Re-evaluate the meta-parellelization method with 
			a longer run. Still, maybe the cost of moving things around is too much.
		- Try having each thread initialize separately. Parse inputs, connect to 
			Julia, etc. Might help..?
"""


def main():
	
	global params
	params = parseArgs()
	params.prefix="out3"
	params.force="fittedD"
	params.variables = ["tmp_dc_cmn", "aet_mm_cyr", "USE"]
	params.seed="1321"
	params.installCS=False
	params.popsize=None
	params.maxpopsize=20
	params.cstype="pairwise"
	params.fitmetric="aic"
	params.predicted=False
	params.inmat=None
	params.cholmod=False
	params.GA_procs=2
	params.CS_procs=1
	params.deltaB=None
	params.deltaB_perc=0.01
	params.nfail=10
	params.maxGens=1
	params.tournsize=5
	params.cxpb=0.5
	params.mutpb=0.3
	params.indpb=0.05
	
	#seed random number generator
	random.seed(params.seed)
	
	#initialize a single-objective GA
	creator.create("FitnessMax", base.Fitness, weights=(1.0,))
	creator.create("Individual", list, fitness=creator.FitnessMax)
	
	#toolbox
	global toolbox
	toolbox = base.Toolbox()
	
	#register GA attributes and type variables
	print("Initializing genetic algorithm parameters...\n")
	initGA(toolbox, params)
	
	#mp.set_start_method("spawn") 
	#pool = mp.Pool(processes=params.GA_procs)
	#toolbox.register("map", pool.map)
	
	#initialize population
	popsize=len(params.variables)*15
	if params.popsize:
		popsize=params.popsize
	if params.maxpopsize and popsize > params.maxpopsize:
		popsize=params.maxpopsize
	popsize=8
	pop = toolbox.population(n=popsize)
	
	# Evaluate the entire population
	print("Evaluating initial population...\n")
	#model_files = [toolbox.evaluate(i, ind) for i, ind in enumerate(pop)]
	#parallel version... not working right now
	# model_files = list(map(toolbox.evaluate, pop))
	# print(model_files)
	# fitnesses = parallel_eval(jl, model_files, params.cstype)
	# print(fitnesses)
	# for ind, fit in zip(pop, fitnesses):
	# 	ind.fitness.values = (fit,)
	fitnesses = list(map(toolbox.evaluate, pop))
	for ind, fit in zip(pop, fitnesses):
		ind.fitness.values = fit

	#sys.exit()
	# CXPB  is the probability with which two individuals are crossed
	# MUTPB is the probability for mutating an individual
	cxpb, mutpb = params.cxpb, params.mutpb
	
	# Extracting all the fitnesses of population
	fits = [ind.fitness.values[0] for ind in pop]
	
	# Variable keeping track of the number of generations
	g = 0

	# Begin the evolution
	#NOTE: Need to implement some sort of callback for 
	
	print("Starting optimization...\n")
	stop=False
	fails=0
	#while max(fits) < 5 and g < 5:
	while fails < params.nfail and g < params.maxGens:
		# A new generation
		g = g + 1
		print("-- Generation %i --" % g)
		
		# Select the next generation individuals
		offspring = toolbox.select(pop, len(pop))
		# Clone the selected individuals
		offspring = list(map(toolbox.clone, offspring))
		
		# Apply crossover and mutation on the offspring
		for child1, child2 in zip(offspring[::2], offspring[1::2]):
			if random.random() < cxpb:
				toolbox.mate(child1, child2)
				del child1.fitness.values
				del child2.fitness.values
		
		for mutant in offspring:
			if random.random() < mutpb:
				toolbox.mutate(mutant)
				del mutant.fitness.values
		
		#evaluate individuals with invalid fitness
		invalid_ind = [ind for ind in offspring if not ind.fitness.valid]
		fitnesses = map(toolbox.evaluate, invalid_ind)
		for ind, fit in zip(invalid_ind, fitnesses):
			ind.fitness.values = fit
		
		#replace population with offspring
		pop[:] = offspring
		
		# Gather all the fitnesses in one list and print the stats
		fits = [ind.fitness.values[0] for ind in pop]

		length = len(pop)
		mean = sum(fits) / length
		sum2 = sum(x*x for x in fits)
		std = abs(sum2 / length - mean**2)**0.5

		print("  Min %s" % min(fits))
		print("  Max %s" % max(fits))
		print("  Avg %s" % mean)
		print("  Std %s" % std)
		
		#evaluate for stopping criteria
		
		
	best = pop[np.argmax([toolbox.evaluate(x) for x in pop])]
	print(best)
	
	#pool.close()

def initialize_worker(params, seed):
	my_number = 1
	
	#make new random seed, as seed+Process_number
	random.seed(seed+my_number)
	
	#make "local" globals (i.e. global w.r.t each process)
	global jl
	global graph
	global distances
	global predictors
	global inc_matrix
	global points
	global gendist
	
	#establish connection to julia
	if my_number == 1:
		print("Attempting to establish connection to Julia...\n")
	global jl
	jl = Julia()
	
	#if params.GA_procs>1:
	if params.installCS:
		if my_number == 1:
			print("Installing Circuitscape.jl... May take a few minutes\n")
		jl.eval("using Pkg; Pkg.add(\"Circuitscape\");")
	if my_number == 1:
		print("Loading Circuitscape in Julia...\n")
	jl.eval("using Pkg; using Distributed; ")
	jl.eval("using Circuitscape; using Suppressor;")
	Main.eval("stdout")

	#read autoStreamTree outputs
	if my_number == 1:
		print("Reading network from: ", network)
	graph = readNetwork((str(params.prefix)+".network"))
	if my_number==1:
		print("Reading autoStreamTree results from:", streamtree)
	(distances, predictors) = readStreamTree((str(params.prefix)+".streamtree.txt"), params.variables, params.force)
	points = readPointCoords((str(params.prefix)+".pointCoords.txt"))
	
	#make sure points are snapped to the network
	snapped=SortedDict()
	for point in points.keys():
		if point not in graph.nodes():
			node=snapToNode(graph, point)
			if my_number == 1:
				print("Point not found in graph, snapping to nearest node:", point, " -- ", node)
			snapped[tuple(node)]=points[point]
		else:
			snapped[tuple(point)]=points[point]
	points = snapped
	del snapped
	
	#read genetic distances
	if params.cstype=="pairwise":
		if params.predicted:
			if my_number == 1:
				print("Reading incidence matrix from: ", inc)
			inc_matrix = readIncidenceMatrix((str(params.prefix)+".incidenceMatrix.txt"))
			gendist = generatePairwiseDistanceMatrix(graph, points, inc_matrix, distances)
		else:
			gendist = parseInputGenMat(graph, points, prefix=params.prefix, inmat=params.inmat)
	

def checkFormatGenMat(mat, order):
	if os.path.isfile(mat):
		#read and see if it has the correct dimensions
		inmat = pd.read_csv(mat, header=0, index_col=0, sep="\t")
		#if correct dimensions, check if labelled correctly
		if len(inmat.columns) >= len(order):
			if set(list(inmat.columns.values)) != set(list(inmat.columns.values)):
				#print("columns and rows don't match")
				return(None)
			# elif set(list(inmat.columns.values)) != set(order):
			# 	#print("Oh no! Input matrix columns and/ or rows don't appear to be labelled properly. Please provide an input matrix with column and row names!")
			# 	return(None)
			else:
				#this must be the one. Reorder it and return
				#print("Reading genetic distances from input matrix:",indmat)
				formatted = inmat.reindex(order)
				formatted = formatted[order]
				#print(formatted)
				gen = formatted.to_numpy()
				return(gen)
		#otherwise, skip and try the popgenmat
		else:
			#print("wrong number of columns")
			return(None)
	else:
		return(None)
		
def parseInputGenMat(graph, points, prefix=None, inmat=None):
	order = getNodeOrder(graph, points, as_list=True)
	#if no input matrix provided, infer from autoStreamTree output
	if not inmat:
		#check if pop and ind mats both exist
		indmat = str(prefix) + ".indGenDistMat.txt"
		popmat = str(prefix) + ".popGenDistMat.txt"
		#if indmat exists
		ind = checkFormatGenMat(indmat, order)
		pop = checkFormatGenMat(popmat, order)
		#print(pop)
		#print(order)
		if pop is not None:
			return(pop)
		elif ind is not None:
			return(ind)
		else:
			print("Failed to read autoStreamTree genetic distance matrix.")
			sys.exit()
	else:
		#read input matrix instead
		gen = checkFormatGenMat(inmat)
		if gen is not None:
			return(gen)
		else:
			print("Failed to read input genetic distance matrix:",inmat)
			sys.exit()

def getNodeOrder(graph, points, as_dict=False, as_index=False, as_list=True):
	node_dict=OrderedDict()
	point_dict=OrderedDict()
	order=list()
	node_idx=0
	#print(type(list(points.keys())[0]))
	for edge in graph.edges():
		left = edge[0]
		right = edge[1]
		#print(type(left))
		#print(type(right))
		if left not in node_dict.keys():
			#print("not in dict")
			if left in points.keys():
				node_dict[left] = node_idx
				order.append(points[left])
				point_dict[left] = points[left]
				node_idx+=1
		if right not in node_dict.keys():
			if right in points.keys():
				node_dict[right] = node_idx
				order.append(points[right])
				point_dict[right] = points[right]
				node_idx+=1
	#if as_index return ordered dict of indices
	if as_index:
		return(node_dict)
	#if as_dict return ordered dict of node names
	if as_dict:
		return(point_dict)
	if as_list:
		return(order)
	#otherwise, return list of NAMES in correct order
	return(order)

def generatePairwiseDistanceMatrix(graph, points, inc_matrix, distances):
	node_dict=getNodeOrder(graph, points, as_index=True)
	gen=np.zeros(shape=(len(points), len(points)))
	inc_row=0
	#print(node_dict.keys())
	#print(node_dict[tuple(list(points.keys())[0])])
	for ia, ib in itertools.combinations(range(0,len(points)),2):
		inc_streams=inc_matrix[inc_row,]
		#print(distances*inc_streams)
		d=sum(distances*inc_streams)
		#print(d)
		inc_row+=1
		#print(node_dict)
		#print(ia, " -- ", list(points.keys())[ia], " -- ", node_dict[list(points.keys())[ia]])
		#print(ib, " -- ", list(points.keys())[ib], " -- ", node_dict[list(points.keys())[ib]])
		gen[node_dict[list(points.keys())[ia]], node_dict[list(points.keys())[ib]]] = d
	#print(gen)
	return(gen)


def readIncidenceMatrix(inc):
	df = pd.read_csv(inc, header=None, index_col=False, sep="\t")
	return(df.to_numpy())
	
def readNetwork(network):
	graph=nx.OrderedGraph(nx.read_gpickle(network).to_undirected())
	return(graph)

#Input: Tuple of [x,y] coordinates
#output: Closest node to those coordinates
def snapToNode(graph, pos):
	#rint("closest_node call:",pos)
	nodes = np.array(graph.nodes())
	node_pos = np.argmin(np.sum((nodes - pos)**2, axis=1))
	#print(nodes)
	#print("closest to ", pos, "is",tuple(nodes[node_pos]))
	return (tuple(nodes[node_pos]))

def readPointCoords(pfile):
	d=SortedDict()
	first=True
	with open(pfile, "r") as pfh:
		for line in pfh:
			if first:
				first=False
				continue
			stuff=line.split()
			name=stuff[0]
			coords=tuple([float(stuff[2]), float(stuff[1])])
			d[coords]=name
	return(d)

def readStreamTree(streamtree, variables, force=None):
	df = pd.read_csv(streamtree, header=0, index_col=False, sep="\t")
	
	df = df.groupby('EDGE_ID').agg('mean')

	#get distances (as a list, values corresponding to nodes)
	if force:
		dist=df[force].tolist()
	else:
		#get locus columns
		filter_col = [col for col in df if col.startswith('locD_')]
		data = df[filter_col]
		
		#aggregate distances
		dist = data.mean(axis=1).tolist()
	
	env=trans.rescaleCols(df[variables], 0, 10)
	return(dist, env)


# #parallel version; actually returns a list of filenames
# #custom evaluation function
# def evaluate(individual):
# 	#vector to hold values across edges
# 	fitness=None
# 	multi=None
# 	first=True 
# 
# 	#build multi-surface
# 	for i, variable in enumerate(predictors.columns):
# 		#Perform variable transformations (if desired)
# 		#1)Scale to 0-10; 2) Perform desired transformation; 3) Re-scale to 0-10
# 		#	NOTE: Get main implementation working first
# 		#add weighted variable data to multi
# 		if individual[0::2][i] == 1:
# 			if first:
# 				multi = predictors[variable]*(individual[1::2][i])
# 				first=False
# 			else:
# 				multi += predictors[variable]*(individual[1::2][i])
# 
# 	#If no layers are selected, return a zero fitness
# 	if first:
# 		fitness = None
# 	else:
# 		#Rescale multi for circuitscape
# 		multi = rescaleCols(multi, 1, 10)
# 
# 		#write circuitscape inputs
# 		oname=".temp"+str(params.seed)+"_"+str(random.randint(1, 100000))
# 		#oname=".temp"+str(params.seed)
# 		focal=True
# 		if params.cstype=="edgewise":
# 			focal=False
# 		cs.writeCircuitScape(oname, graph, points, multi, focalPoints=focal, fromAttribute=None)
# 		cs.writeIni(oname, cholmod=params.cholmod, parallel=int(params.CS_procs))
# 
# 		fitness=oname
# 	#return fitness value
# 	return(fitness)
# 
# def parallel_eval(jl, ini_list, cstype):
# 	#Call circuitscape from pyjulia
# 	results = cs.evaluateIniParallel(jl, ini_list)
# 
# 	#parse circuitscape output
# 	fitnesses = list()
# 	for ini in ini_list:
# 		fitness = 0
# 		if ini is None:
# 			fitness = float('-inf')
# 		else:
# 			if cstype=="edgewise":
# 				res = cs.parseEdgewise(ini, distances)
# 				fitness = res[params.fitmetric][0]
# 			else:
# 				res = cs.parsePairwise(ini, gendist)
# 				fitness = res[params.fitmetric][0]
# 			#cs.cleanup(ini)
# 		fitnesses.append(fitness)
# 	return(fitnesses)

def transform(dat, transformation, shape):
	d=dat
	if transformation <= 0:
		pass
	elif transformation == 1:
		d=trans.ricker(dat, shape, 10)
	elif transformation == 2:
		d=trans.revRicker(dat, shape, 10)
	elif transformation == 3:
		d=trans.invRicker(dat, shape, 10)
	elif transformation == 4:
		d=trans.revInvRicker(dat, shape, 10)
	elif transformation == 5:
		d=trans.monomolecular(dat, shape, 10)
	elif transformation == 6:
		d=trans.revMonomolecular(dat, shape, 10)
	elif transformation == 7:
		d=trans.invMonomolecular(dat, shape, 10)
	elif transformation == 8:
		d=trans.revMonomolecular(dat, shape, 10)
	else:
		print("WARNING: Invalid transformation type. Returning un-transformed data.")
	return(trans.rescaleCols(d, 0, 10))

# Version for doing each individual serially
# #custom evaluation function
def evaluate(individual):
	#vector to hold values across edges
	fitness=0
	multi=None
	first=True 

	#build multi-surface
	for i, variable in enumerate(predictors.columns):
		#Perform variable transformations (if desired)
		#1)Scale to 0-10; 2) Perform desired transformation; 3) Re-scale to 0-10
		#	NOTE: Get main implementation working first
		#add weighted variable data to multi
		if individual[0::4][i] == 1:
			#print("Before:", predictors[variable])
			var = transform(predictors[variable], individual[2::4][i], individual[3::4][i])
			#print("Before:", var)
			if first:
				#transform(data, transformation, shape) * weight
				multi = var*(individual[1::4][i])
				first=False
			else:
				multi += var*(individual[1::4][i])

	#If no layers are selected, return a zero fitness
	if first:
		fitness = float('-inf')
	else:
		#Rescale multi for circuitscape
		#print("Multi:",multi)
		multi = trans.rescaleCols(multi, 1, 10)

		#write circuitscape inputs
		#oname=".temp"+str(params.seed)+"_"+str(mp.Process().name)
		oname=".temp"+str(params.seed)
		focal=True
		if params.cstype=="edgewise":
			focal=False
		cs.writeCircuitScape(oname, graph, points, multi, focalPoints=focal, fromAttribute=None)
		cs.writeIni(oname, cholmod=params.cholmod, parallel=int(params.CS_procs))

		#Call circuitscape from pyjulia
		cs.evaluateIni(jl, oname)

		#parse circuitscape output
		if params.cstype=="edgewise":
			res = cs.parseEdgewise(oname, distances)
			fitness = res[params.fitmetric][0]
		else:
			res = cs.parsePairwise(oname, gendist)
			fitness = res[params.fitmetric][0]
	#return fitness value
	return(fitness,)

#custom mutation function
#To decide: Should the current state inform the next state, or let it be random?
#May depend on the "gene"?
def mutate(individual, indpb):
	for (i, variable) in enumerate(predictors.columns):
		if random.random() < indpb:
			individual[0::4][i] = toolbox.feature_sel()
		if random.random() < indpb:
			individual[1::4][i] = toolbox.feature_weight()
		if random.random() < indpb:
			individual[2::4][i] = toolbox.feature_transform()
		if random.random() < indpb:
			individual[3::4][i] = toolbox.feature_shape()
	return(individual,)

def initGA(toolbox, params):
	#register attributes
	toolbox.register("feature_sel", random.randint, 0, 1)
	toolbox.register("feature_weight", random.uniform, -1.0, 1.0)
	toolbox.register("feature_transform", random.randint, 0, 8)
	toolbox.register("feature_shape", random.randint, 1, 100)
	
	#register type for individuals 
	#these consist of chromosomes of i variables x j attributes (above)
	toolbox.register("individual", tools.initCycle, creator.Individual,(toolbox.feature_sel, toolbox.feature_weight, toolbox.feature_transform, toolbox.feature_shape), n=len(params.variables))
	#toolbox.register("individual", tools.initRepeat, creator.Individual, toolbox.feature_sel, n=len(params.variables))
	
	#register type for populations
	#these are just a list of individuals
	toolbox.register("population", tools.initRepeat, list, toolbox.individual)	

	#register custom evaluation function
	toolbox.register("evaluate", evaluate)
	
	#register mating function
	toolbox.register("mate", tools.cxTwoPoint)
	
	#register mutation function
	toolbox.register("mutate", mutate, indpb=params.indpb) #NOTE: make indpb an argument
	
	#register tournament function
	toolbox.register("select", tools.selTournament, tournsize=5) #NOTE: Make tournsize an argument

#Call main function
if __name__ == '__main__':
	main()