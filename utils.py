import os
import csv
import numpy as np
from fastdtw import fastdtw
from torch.utils.data import Dataset, DataLoader
from tqdm import tqdm
import torch


files = {
    'pems03': ['PEMS03/PEMS03.npz', 'PEMS03/PEMS03.csv'],
    'pems04': ['PEMS04/PEMS04.npz', 'PEMS04/PEMS04.csv'],
    'pems07': ['PEMS07/PEMS07.npz', 'PEMS07/PEMS07.csv'],
    'pems08': ['PEMS08/PEMS08.npz', 'PEMS08/PEMS08.csv'],
    'pemsbay': ['PEMSBAY/pems_bay.npz', 'PEMSBAY/distance.csv'],
    'pemsD7M': ['PeMSD7M/PeMSD7M.npz', 'PeMSD7M/distance.csv'],
    'pemsD7L': ['PeMSD7L/PeMSD7L.npz', 'PeMSD7L/distance.csv']
}


def read_data(args):
    """read data, generate spatial adjacency matrix and semantic adjacency matrix by dtw

    Args:
        sigma1: float, default=0.1, sigma for the semantic matrix
        sigma2: float, default=10, sigma for the spatial matrix
        thres1: float, default=0.6, the threshold for the semantic matrix
        thres2: float, default=0.5, the threshold for the spatial matrix

    Returns:
        data: tensor, T * N * 1
        dtw_matrix: array, semantic adjacency matrix
        sp_matrix: array, spatial adjacency matrix
    """
    filename = args.filename
    file = files[filename]
    filepath = "./data/"
    if args.remote:
        filepath = '/home/lantu.lqq/ftemp/data/'
    data = np.load(filepath + file[0])['data']
    data_cp=data
    # PEMS04 == shape: (16992, 307, 3)    feature: flow,occupy,speed
    # PEMSD7M == shape: (12672, 228, 1)
    # PEMSD7L == shape: (12672, 1026, 1)
    num_node = data.shape[1]
    mean_value = np.mean(data, axis=(0, 1)).reshape(1, 1, -1)
    std_value = np.std(data, axis=(0, 1)).reshape(1, 1, -1)
    data = (data - mean_value) / std_value
    mean_value = mean_value.reshape(-1)[0]
    std_value = std_value.reshape(-1)[0]

    
    #Create DTW graph
    if not os.path.exists(f'data/{filename}_dtw_distance.npy'):
        data_mean = np.mean([data[:, :, 0][24*12*i: 24*12*(i+1)] for i in range(data.shape[0]//(24*12))], axis=0)
        data_mean = data_mean.squeeze().T 
        dtw_distance = np.zeros((num_node, num_node))
        for i in tqdm(range(num_node)):
            for j in range(i, num_node):
                dtw_distance[i][j] = fastdtw(data_mean[i], data_mean[j], radius=6)[0]
        for i in range(num_node):
            for j in range(i):
                dtw_distance[i][j] = dtw_distance[j][i]
        np.save(f'data/{filename}_dtw_distance.npy', dtw_distance)

    dist_matrix = np.load(f'data/{filename}_dtw_distance.npy')

    mean = np.mean(dist_matrix)
    std = np.std(dist_matrix)
    dist_matrix = (dist_matrix - mean) / std
    sigma = args.sigma1
    dist_matrix = np.exp(-dist_matrix ** 2 / sigma ** 2)
    dtw_matrix = np.zeros_like(dist_matrix)
    dtw_matrix[dist_matrix > args.thres1] = 1



    
    # use continuous spatial matrix
    if not os.path.exists(f'data/{filename}_spatial_distance.npy'):
        with open(filepath + file[1], 'r') as fp:
            dist_matrix = np.zeros((num_node, num_node)) + np.float64('inf')
            file = csv.reader(fp)
            for line in file:
                break
            for line in file:
                start = int(line[0])
                end = int(line[1])
                dist_matrix[start][end] = float(line[2])
                dist_matrix[end][start] = float(line[2])
            np.save(f'data/{filename}_spatial_distance.npy', dist_matrix)

    dist_matrix = np.load(f'data/{filename}_spatial_distance.npy')
    # normalization
    std = np.std(dist_matrix[dist_matrix != np.float64('inf')])
    mean = np.mean(dist_matrix[dist_matrix != np.float64('inf')])
    dist_matrix = (dist_matrix - mean) / std
    sigma = args.sigma2
    sp_matrix = np.exp(- dist_matrix**2 / sigma**2)
    sp_matrix[sp_matrix < args.thres2] = 0

    print(f'average degree of spatial graph is {np.sum(sp_matrix > 0)/2/num_node}')
    print(f'average degree of semantic graph is {np.sum(dtw_matrix > 0)/2/num_node}')
    return torch.from_numpy(data_cp.astype(np.float64)), mean_value, std_value, dtw_matrix, sp_matrix


def get_normalized_adj(A):
    """
    Returns a tensor, the degree normalized adjacency matrix.
    """
    alpha = 0.8
    D = np.array(np.sum(A, axis=1)).reshape((-1,))
    D[D <= 10e-5] = 10e-5    # Prevent infs
    diag = np.reciprocal(np.sqrt(D))
    A_wave = np.multiply(np.multiply(diag.reshape((-1, 1)), A),
                         diag.reshape((1, -1)))
    A_reg = alpha / 2 * (np.eye(A.shape[0]) + A_wave)
    return torch.from_numpy(A_reg.astype(np.float64))



def generate_graph_seq2seq_io_data(
        data, x_offsets, y_offsets
):
    """

    :param data:  [B, N, D]
    :param x_offsets:
    :param y_offsets:
    :return:
    """
    num_samples, num_nodes = data.shape
    data = data[:, :]

    x, y = [], []
    min_t = abs(min(x_offsets))  # 11
    max_t = abs(num_samples - abs(max(y_offsets)))  # num_samples - 12

    for t in tqdm(range(min_t, max_t)):
        x_t = data[t + x_offsets, ...]


        x.append(x_t)


    x = np.stack(x, axis=0)  # [B, T, N ,C]


    return x
def std_mean(data):

    seq_length_x = 12
    seq_length_y = 12
    y_start=1
    x_offsets = np.arange(-(seq_length_x - 1), 1, 1)
    y_offsets = np.arange(y_start, (seq_length_y + 1), 1)
    data = generate_graph_seq2seq_io_data(data=data, x_offsets=x_offsets, y_offsets=y_offsets)
    mean_value = np.mean(data)
    std_value = np.std(data)
    print(mean_value, std_value)
    data = (data - mean_value) / std_value
    del data
    return mean_value,std_value

class MyDataset(Dataset):
    def __init__(self, data, split_start, split_end, his_length, pred_length,mean,std):
        split_start = int(split_start)
        split_end = int(split_end)
        self.mean=mean
        self.std=std

        self.data = data[split_start: split_end]
        self.his_length = his_length
        self.pred_length = pred_length

    def __getitem__(self, index):
        x = self.data[index: index + self.his_length].permute(1, 0, 2)
        x=(x - self.mean) / self.std
        y = self.data[index + self.his_length: index + self.his_length + self.pred_length][:, :, 0].permute(1, 0)
        return torch.Tensor(x), torch.Tensor(y)
    def __len__(self):
        return self.data.shape[0] - self.his_length - self.pred_length + 1


def generate_dataset(data, args):
    """
    Args:
        data: input dataset, shape like T * N
        batch_size: int 
        train_ratio: float, the ratio of the dataset for training
        his_length: the input length of time series for prediction
        pred_length: the target length of time series of prediction

    Returns:
        train_dataloader: torch tensor, shape like batch * N * his_length * features
        test_dataloader: torch tensor, shape like batch * N * pred_length * features
    """
    batch_size = args.batch_size
    train_ratio = args.train_ratio
    valid_ratio = args.valid_ratio
    his_length = args.his_length
    pred_length = args.pred_length

    train_mean,train_std=std_mean(data[0: int(data.shape[0] * train_ratio),...,-1])
    train_dataset = MyDataset(data, 0, data.shape[0] * train_ratio, his_length, pred_length,train_mean,train_std)
    train_dataloader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)

    #-------------------------normal version--------------------------#

    val_mean, val_std = std_mean(data[int(data.shape[0]*train_ratio): int(data.shape[0]*(train_ratio+valid_ratio)),...,-1])
    valid_dataset = MyDataset(data, data.shape[0]*train_ratio, data.shape[0]*(train_ratio+valid_ratio), his_length, pred_length,val_mean, val_std)
    valid_dataloader = DataLoader(valid_dataset, batch_size=batch_size, shuffle=True)

    # -------------------------effective version--------------------------#

    # val_mean, val_std = std_mean(data[int(data.shape[0] * (train_ratio + valid_ratio)):data.shape[0],...,-1])
    # valid_dataset = MyDataset(data, data.shape[0]*(train_ratio+valid_ratio), data.shape[0], his_length, pred_length,val_mean, val_std)
    # valid_dataloader = DataLoader(valid_dataset, batch_size=batch_size, shuffle=True)


    test_mean, test_std = std_mean(data[int(data.shape[0] * (train_ratio + valid_ratio)):data.shape[0],...,-1])
    test_dataset = MyDataset(data, data.shape[0]*(train_ratio+valid_ratio), data.shape[0], his_length, pred_length,test_mean, test_std)
    test_dataloader = DataLoader(test_dataset, batch_size=batch_size, shuffle=True)

    return train_dataloader, valid_dataloader, test_dataloader,train_mean,train_std,val_mean,val_std,test_mean,test_std
