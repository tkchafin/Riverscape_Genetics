import os
import sys
import pandas as pd 
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt

import warnings
warnings.simplefilter('ignore', category=UserWarning)

class hallOfFame():
	def __init__(self, variables, max_size, init_pop=None):
		cols=list()
		cols.append("fitness")
		for v in variables:
			cols.append(str(v))
			cols.append(str(v)+"_weight")
			cols.append(str(v)+"_trans")
			cols.append(str(v)+"_shape")
		cols.append("loglik")
		cols.append("r2m")
		cols.append("aic")
		cols.append("delta_aic_null")
		self.data = pd.DataFrame(columns=cols)
		self.variables=variables
		self.max_size=int(max_size)
		self.min_fitness=float('-inf')
		self.rvi=pd.DataFrame(columns=['variable', 'RVI'])
		
		if init_pop is not None:
			self.check_population(init_pop)
			
	def check_population(self, pop):
		popDF = pd.DataFrame(pop, columns=self.data.columns)
		popDF = popDF[popDF.fitness > float('-inf')]
		if popDF.shape[0] < 1:
			return
		popDF = popDF.sort_values('fitness', ascending=False)
		popDF = popDF.drop_duplicates(keep='first', ignore_index=True)
		space = self.max_size - self.data.shape[0]
		
		if space > 0:
			#print('hall of fame not full')
			select_size=space
			if space> popDF.shape[0]:
				select_size=popDF.shape[0]
			self.data = self.data.append(popDF[:select_size], ignore_index=True)
			self.min_fitness = self.data['fitness'].min()
		else:
			if popDF['fitness'].max() > self.min_fitness:
				subset=popDF[popDF.fitness > self.min_fitness]
				self.data = self.data.append(subset, ignore_index=True)
				self.data = self.data.sort_values('fitness', ascending=False)
				self.data = self.data.drop_duplicates(keep='first', ignore_index=True)
				if self.data.shape[0] > self.max_size:
					self.data = self.data[:self.max_size]
				self.min_fitness = self.data['fitness'].min()
			else:
				return
	
	def printHOF(self, max_row=None, max_col=None):
		self.data = self.data.sort_values('fitness', ascending=False)
		with pd.option_context('display.max_rows', max_row, 'display.max_columns', max_col):  # more options can be specified also
			print(self.data)
	
	def printRVI(self, max_row=None, max_col=None):
		self.rvi = self.rvi.sort_values('RVI', ascending=False)
		with pd.option_context('display.max_rows', max_row, 'display.max_columns', max_col):  # more options can be specified also
			print(self.rvi)
	
	def delta_aic(self):
		if self.data.shape[0] <= 0:
			return
		if "delta_aic_best" in self.data.columns:
			return
		else:
			self.data["aic"] = self.data["aic"]*-1 #reverse the neg sign i added for maximizing
			best=self.data["aic"].min()
			self.data["delta_aic_best"] = self.data["aic"]-best
	
	def correct_aic_fitness(self):
		self.data["fitness"] = self.data["fitness"]*-1
	
	def akaike_weights(self):
		if self.data.shape[0] <= 0:
			return
		if "delta_aic_best" not in self.data.columns:
			self.delta_aic()
		#weight(i) = e^(-1/2 delta_aic_best) / sum(e^(-1/2 delta_aic_best(k)))
		#where the denominator is summed over k models
		#delta_aic = self.data["delta_aic_best"].to_numpy()
		#sum_k = self.data["delta_aic_best"].to_numpy()
		#did a test agains MuMIn::Weights in R and this seems to be working
		self.data["akaike_weight"]=((np.exp(-0.5*self.data["delta_aic_best"])) / (sum(np.exp(-0.5*self.data["delta_aic_best"]))))
	
	def cumulative_akaike(self, threshold=1.0):
		if self.data.shape[0] <= 0:
			return
		threshold=float(threshold)
		if "akaike_weight" not in self.data.columns:
			self.akaike_weights()
		self.data["acc_akaike_weight"] = self.data["akaike_weight"].cumsum()
		if threshold > 0.0 and threshold < 1.0:
				if self.data["acc_akaike_weight"].max() > threshold:
					cutoff=self.data[self.data["acc_akaike_weight"].gt(threshold)].index[0]
					keep_vals = ["False"]*self.data.shape[0]
					keep_vals[:(cutoff+1)] = ["True"]*(cutoff+1)
					self.data["keep"] = keep_vals #+1 b/c above is 0-based index
				else:
					keep_vals = ["True"]*self.data.shape[0]
					self.data["keep"] = keep_vals
		else:
			keep_vals = ["True"]*self.data.shape[0]
			self.data["keep"] = keep_vals

	def relative_variable_importance(self,ignore_keep=False):
		#clear previous calculations
		self.rvi=pd.DataFrame(columns=['variable', 'RVI'])
		sub=self.data[self.data.keep=="True"]
		if ignore_keep:
			sub=self.data
		#compute sum of weights
		for v in self.variables:
			sw=(sub[v]*sub['akaike_weight']).sum()
			self.rvi.loc[len(self.rvi), :] = [v, sw]
		self.rvi = self.rvi.sort_values('RVI', ascending=False)
	
	def cleanHOF(self):
		for v in self.variables:
			data[data.v == 0][(str(v)+"_weight")] = "NaN"
			data[data.v == 0][(str(v)+"_trans")] = "NaN"
			data[data.v == 0][(str(v)+"_shape")] = "NaN"
	
	def getRVI(self):
		self.rvi = self.rvi.sort_values('RVI', ascending=False)
		return(self.rvi)
	
	def getHOF(self, only_keep=False):
		self.data = self.data.sort_values('fitness', ascending=False)
		if only_keep:
			return(self.data[self.data.keep=="True"])
		else:
			return(self.data)
	
	def output(self):
		#Make sure to remove weights/ shapes where variable isn't selected
		#get absolute value of AIC (made them negative so all metrics could use maximize function)
		pass
	
	def plot_ICprofile(self, oname="out", diff=2):
		pass
		diff=int(diff)
		#X axis - order by AIC.
		dat=self.data.sort_values('aic', ascending=True)
		dat = dat.round(3)
		dat.reset_index()
		dat["model"]=dat.index + 1
		#y axis - AIC value
		sns.set(style="ticks")
		p = sns.scatterplot(data=dat, x="model", y="aic", hue="r2m", size="r2m", style="keep",  alpha=0.6)
		p.axhline((dat["aic"].min()+diff), ls="--", c="red")
		plt.title("IC Profile")
		plt.savefig((str(oname)+".ICprofile.pdf"))
		plt.clf()
	
	def plotMetricPW(self, oname="out"):
		cols=["aic", "loglik", "r2m", "delta_aic_null", "keep"]
		if "akaike_weight" in self.data.columns:
			cols.append("akaike_weight")
		dat=self.data[cols]
		sns.pairplot(dat, hue="keep", kind="scatter")
		plt.savefig((str(oname)+".pairPlot.pdf"))
		plt.clf()
	
	def plotVariableImportance(self, oname="out", cutoff=0.8):
		cutoff=float(cutoff)
		sub=self.rvi.sort_values('RVI', ascending=False)
		p=sns.barplot(data=sub, x="RVI", y="variable")
		p.axvline(cutoff, ls="--", c="red")
		plt.title("Importance of Terms")
		plt.savefig((str(oname)+".varImportance.pdf"))
		plt.clf()
	
	def writeModelSummary(self):
		pass
		#plot models in the format "A+B+C", etc
