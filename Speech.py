"""
@author: Maziar Raissi
Ayumu Oaku aoaku1@sheffield.ac.uk

Job script
qrshx -l gpu=1
module load apps/python/conda
module load libs/cudnn/7.5.0.56/binary-cuda-10.0.130
source activate tensorflow-gpu
"""
# To submit batch GPU jobs
#!/bin/bash
#$ -l gpu=1

import tensorflow as tf
import numpy as np
import time
import scipy.io
from scipy.io.wavfile import read, write
from scipy.interpolate import griddata
from pyDOE import lhs

np.random.seed(1234)
tf.set_random_seed(1234)

class PhysicsInformedNN:
    # Initialize the class
    def __init__(self, X_u, u, X_f, layers, lb, ub, nu):
        
        self.lb = lb
        self.ub = ub
    
        self.x_u = X_u[:,0:1]
        self.t_u = X_u[:,1:2]
        
        #take cord xf
        self.x_f = X_f[:,0:1]
        self.t_f = X_f[:,1:2]
        
        self.u = u
        
        self.layers = layers
        self.nu = nu
        
        # Initialize NNs
        self.weights, self.biases = self.initialize_NN(layers)
        
        # tf placeholders and graph
        self.sess = tf.Session(config=tf.ConfigProto(allow_soft_placement=True,
                                                     log_device_placement=True))
        
        self.x_u_tf = tf.placeholder(tf.float32, shape=[None, self.x_u.shape[1]])
        self.t_u_tf = tf.placeholder(tf.float32, shape=[None, self.t_u.shape[1]])        
        self.u_tf = tf.placeholder(tf.float32, shape=[None, self.u.shape[1]])
        
        self.x_f_tf = tf.placeholder(tf.float32, shape=[None, self.x_f.shape[1]])
        self.t_f_tf = tf.placeholder(tf.float32, shape=[None, self.t_f.shape[1]])        
                
        self.u_pred = self.net_u(self.x_u_tf, self.t_u_tf) 
        self.f_pred = self.net_f(self.x_f_tf, self.t_f_tf)         
        
        self.loss = tf.reduce_mean(tf.square(self.u_tf - self.u_pred)) + \
                    tf.reduce_mean(tf.square(self.f_pred))

        self.optimizer = tf.contrib.opt.ScipyOptimizerInterface(self.loss, 
                                                                method = 'L-BFGS-B', 
                                                                options = {'maxiter': 50000,
                                                                           'maxfun': 50000,
                                                                           'maxcor': 50,
                                                                           'maxls': 50,
                                                                           'ftol' : 1.0 * np.finfo(float).eps})
        
        init = tf.global_variables_initializer()
        self.sess.run(init)

                
    def initialize_NN(self, layers):        
        weights = []
        biases = []
        num_layers = len(layers) 
        for l in range(0,num_layers-1):
            W = self.xavier_init(size=[layers[l], layers[l+1]])
            b = tf.Variable(tf.zeros([1,layers[l+1]], dtype=tf.float32), dtype=tf.float32)
            weights.append(W)
            biases.append(b)        
        return weights, biases
        
    def xavier_init(self, size):
        in_dim = size[0]
        out_dim = size[1]        
        xavier_stddev = np.sqrt(2/(in_dim + out_dim))
        return tf.Variable(tf.truncated_normal([in_dim, out_dim], stddev=xavier_stddev), dtype=tf.float32)
    
    def neural_net(self, X, weights, biases):
        num_layers = len(weights) + 1
        
        H = 2.0*(X - self.lb)/(self.ub - self.lb) - 1.0
        for l in range(0,num_layers-2):
            W = weights[l]
            b = biases[l]
            H = tf.tanh(tf.add(tf.matmul(H, W), b))
        W = weights[-1]
        b = biases[-1]
        Y = tf.add(tf.matmul(H, W), b)
        return Y
            
    def net_u(self, x, t):
        u = self.neural_net(tf.concat([x,t],1), self.weights, self.biases)
        return u
    
    def net_f(self, x,t):
        u = self.net_u(x,t)
        u_t = tf.gradients(u, t)[0]
        u_x = tf.gradients(u, x)[0]
        u_xx = tf.gradients(u_x, x)[0]
        # Burgers equation
        f = u_t + u*u_x - (0.01/np.pi)*u_xx
        return f
    
    def callback(self, loss):
        print('Loss:', loss)
        
    def train(self):
        
        tf_dict = {self.x_u_tf: self.x_u, self.t_u_tf: self.t_u, self.u_tf: self.u,
                   self.x_f_tf: self.x_f, self.t_f_tf: self.t_f}
        
        self.optimizer.minimize(self.sess, 
                                feed_dict = tf_dict,         
                                fetches = [self.loss], 
                                loss_callback = self.callback)        
                                    
    
    def predict(self, X_star):
                
        u_star = self.sess.run(self.u_pred, {self.x_u_tf: X_star[:,0:1], self.t_u_tf: X_star[:,1:2]})  
        f_star = self.sess.run(self.f_pred, {self.x_f_tf: X_star[:,0:1], self.t_f_tf: X_star[:,1:2]})
        
        return u_star, f_star
    
if __name__ == "__main__": 
    
    # Setting
    N_u = 100   # Initial and boundary condition with the num of learning data
    N_f = 10000 # Collocation points
    fs = 16000  # Sampling freqency
    t = 0.5 # seconds  
    layers = [2, 20, 20, 20, 20, 20, 20, 20, 20, 1]
    
    # Load wav files
    data, samplerate = read("Data/train.wav")
    gold_standard, samplerate = read('Data/aa_DR1_MCPM0_sa1.wav')
    data = scipy.io.loadmat('Data/periodic.mat')
    
    # Initial condition
    t = data['t'].flatten()[:,None]
    x = data['x'].flatten()[:,None]
    X, T = np.meshgrid(x,t)
    X_star = np.hstack((X.flatten()[:,None], T.flatten()[:,None]))

    Exact = np.real(data['usol']).T # usol = u(t,x) solution?
    u_star = Exact.flatten()[:,None]              

    xx1 = np.hstack((X[0:1,:].T, T[0:1,:].T))
    xx2 = np.hstack((X[:,0:1], T[:,0:1]))
    xx3 = np.hstack((X[:,-1:], T[:,-1:]))
    # Input values, x and u in func u(x,t)
    X_u_train = np.vstack([xx1, xx2, xx3])
    
    uu1 = Exact[0:1,:].T
    uu2 = Exact[:,0:1]
    uu3 = Exact[:,-1:]
    # Training data of function u(x,t)
    u_train = np.vstack([uu1, uu2, uu3])

    # Extract the num of Nu with data of Initial condition
    idx = np.random.choice(X_u_train.shape[0], N_u, replace=False)
    X_u_train = X_u_train[idx, :]
    u_train = u_train[idx,:]
    
    # Doman bounds
    lb = X_star.min(0)
    ub = X_star.max(0)  
    # Generate collocation points
    X_f_train = lb + (ub-lb)*lhs(2, N_f)
    X_f_train = np.vstack((X_f_train, X_u_train))

    # Give data to PhysicsInformedNN class
    model = PhysicsInformedNN(X_u_train, u_train, X_f_train, layers, lb, ub)
    
    start_time = time.time()                
    result = model.train()
    elapsed = time.time() - start_time                
    print('Training time: %.4f' % (elapsed))
    
    u_pred, f_pred = model.predict(X_star)
    # Export result as wav file
    #write("a.wav", fs, model.astype(np.int16))


    #-------------------------------------------------------------------------
    #error_u = np.linalg.norm(u_star-u_pred,2)/np.linalg.norm(u_star,2)
    #print('Error u: %e' % (error_u))                     
    
    #U_pred = griddata(X_star, u_pred.flatten(), (X, T), method='cubic')
    #Error = np.abs(Exact - U_pred)