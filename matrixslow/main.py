# -*- coding: utf-8 -*-
"""
Created on Wed July  9 15:13:01 2019

@author: chenzhen
"""
import random
import sys

import matplotlib
import numpy as np
from sklearn.metrics import accuracy_score

from core import Variable
from core.graph import default_graph, get_node_from_graph
from ops import Add, Logistic, MatMul, ReLU, SoftMax
from ops.loss import CrossEntropyWithSoftMax, LogLoss
from ops.metrics import Accuracy, Metrics
from optimizer import *
from trainer import Saver, Trainer
from trainer.dist_trainer import SyncTrainerParameterServer
from util import *
from util import ClassMining

matplotlib.use('TkAgg')
sys.path.append('.')


def plot_data(data_x, data_y, weights=None, bias=None):
    '''
    绘制数据节点和线性模型，只绘制2维或3维
    如果特征维度>3,默认使用前3个特征绘制
    '''
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d import Axes3D
    assert len(data_x) == len(data_y)
    data_dim = data_x.shape[1]
    plot_3d = False if data_dim < 3 else True

    xcord1 = []
    ycord1 = []
    zcord1 = []
    xcord2 = []
    ycord2 = []
    zcord2 = []
    for i in range(data_x.shape[0]):
        if int(data_y[i]) == 1:
            xcord1.append(data_x[i, 0])
            ycord1.append(data_x[i, 1])
            if plot_3d:
                zcord1.append(data_x[i, 2])
        else:
            xcord2.append(data_x[i, 0])
            ycord2.append(data_x[i, 1])
            if plot_3d:
                zcord2.append(data_x[i, 2])
    fig = plt.figure()
    if plot_3d:
        ax = Axes3D(fig)
        ax.scatter(xcord1, ycord1, zcord1, s=30, c='red', marker='s')
        ax.scatter(xcord2, ycord2, zcord2, s=30, c='green')
    else:
        ax = fig.add_subplot(111)
        ax.scatter(xcord1, ycord1, s=30, c='red', marker='s')
        ax.scatter(xcord2, ycord2, s=30, c='green')

    if weights is not None and bias is not None:
        x1 = np.arange(-1.0, 1.0, 0.1)
        if plot_3d:
            x2 = np.arange(-1.0, 1.0, 0.1)
            x1, x2 = np.meshgrid(x1, x2)
        weights = np.array(weights)
        bias = np.array(bias)
        if plot_3d:
            y = (-weights[0][0] * x1 -
                 weights[0][1] * x2 - bias[0][0]) / weights[0][2]
            ax.plot_surface(x1, x2, y)
        else:
            y = (-weights[0][0] * x1 - bias[0][0]) / weights[0][1]
            ax.plot(x1, y)
    plt.show()


def random_gen_dateset(feature_num, sample_num, test_radio=0.3, seed=41):
    '''
    生成二分类样本
    '''
    random.seed(seed)
    rand_bias = np.mat(np.random.uniform(-0.1, 0.1, (sample_num, 1)))
    rand_weights = np.mat(np.random.uniform(-1, 1, (feature_num, 1)))
    data_x = np.mat(np.random.uniform(-1, 1, (sample_num, feature_num)))
    data_y = (data_x * rand_weights) + rand_bias
    data_y = np.where(data_y > 0, 1, 0)
    train_size = int(sample_num * (1 - test_radio))

    return (data_x[:train_size, :],
            data_y[:train_size, :],
            data_x[train_size:, :],
            data_y[train_size:, :])


def build_model(feature_num):
    '''
    构建DNN计算图网络
    '''
    x = Variable((feature_num, 1), init=False,
                 trainable=False, name='placeholder_x')
    w1 = Variable((HIDDEN1_SIZE, feature_num), init=True,
                  trainable=True, name='weights_w1')
    b1 = Variable((HIDDEN1_SIZE, 1), init=True,
                  trainable=True, name='bias_b1')
    w2 = Variable((HIDDEN2_SIZE, HIDDEN1_SIZE), init=True,
                  trainable=True, name='weights_w2')
    b2 = Variable((HIDDEN2_SIZE, 1), init=True,
                  trainable=True, name='bias_b2')
    w3 = Variable((CLASSES, HIDDEN2_SIZE), init=True,
                  trainable=True, name='weights_w3')
    b3 = Variable((CLASSES, 1), init=True,
                  trainable=True, name='bias_b3')

    hidden1 = ReLU(Add(MatMul(w1, x), b1), name='hidden1')
    hidden2 = ReLU(Add(MatMul(w2, hidden1), b2), name='hidden2')
    logit = Add(MatMul(w3, hidden2), b3, name='logits')

    return x, logit, w1, b1


def build_metrics(logits, y, metrics_names=None):
    metrics_ops = []
    for m_name in metrics_names:
        metrics_ops.append(ClassMining.get_instance_by_subclass_name(
            Metrics, m_name)(logits, y, need_save=False))

    return metrics_ops


def train(train_x, train_y, test_x, test_y, epoches, batch_size):

    x, logits, w, b = build_model(FEATURE_DIM)

    y = Variable((CLASSES, 1), init=False,
                 trainable=False, name='placeholder_y')
    loss_op = CrossEntropyWithSoftMax(logits, y, name='loss')
    optimizer_op = optimizer.Adam(default_graph, loss_op)
    trainer = SyncTrainerParameterServer(x, y, logits, loss_op, optimizer_op,
                                         epoches=epoches, batch_size=batch_size,
                                         eval_on_train=True,
                                         metrics_ops=build_metrics(
                                             logits, y, ['Accuracy', 'Recall', 'F1Score', 'Precision']))

    trainer.train(train_x, train_y, test_x, test_y)

    saver = Saver('./export')
    saver.save(model_file_name='my_model.json',
               weights_file_name='my_weights.npz')

    return w, b


def inference_after_building_model(test_x, test_y):
    '''
    提前构建计算图，再把保存的权值恢复到新构建的计算图中
    要求构建的计算图必须与原计算图保持完全一致
    '''
    # 重新构建计算图
    x, logits, w, b = build_model(FEATURE_DIM)
    y = Variable((CLASSES, 1), init=False,
                 trainable=False, name='placeholder_y')

    # 从文件恢复模型
    saver = Saver('./export')
    saver.load(model_file_name='my_model.json',
               weights_file_name='my_weights.npz')

    accuracy = Accuracy(logits, y)

    for index in range(len(test_x)):
        features = test_x[index]
        label_onehot = test_y[index]
        x.set_value(np.mat(features).T)
        y.set_value(np.mat(label_onehot).T)

        logits.forward()
        accuracy.forward()

        pred = np.argmax(logits.value)
        gt = np.argmax(y.value)
        if pred != gt:
            print('prediction: {} and groudtruch: {} '.format(pred, gt))
    print('accuracy: {}'.format(accuracy.value))


def inference_without_building_model(test_x, test_y):
    '''
    不需要构建计算图，完全从保存的文件中把计算图和相应的权值恢复
    如果要使用计算图，需要通过节点名称，调用get_node_from_graph获取相应的节点引用
    '''
    saver = Saver('./export')
    saver.load(model_file_name='my_model.json',
               weights_file_name='my_weights.npz')

    x = get_node_from_graph('placeholder_x')
    y = get_node_from_graph('placeholder_y')
    logits = get_node_from_graph('logits')
    accuracy = Accuracy(logits, y)

    for index in range(len(test_x)):
        features = test_x[index]
        label_onehot = test_y[index]
        x.set_value(np.mat(features).T)
        y.set_value(np.mat(label_onehot).T)

        logits.forward()
        accuracy.forward()

        pred = np.argmax(logits.value)
        gt = np.argmax(y.value)
        if pred != gt:
            print('False prediction: {} and groudtruch: {} '.format(pred, gt))
    print('accuracy: {}'.format(accuracy.value))


FEATURE_DIM = 784
TOTAL_EPOCHES = 5
BATCH_SIZE = 8
HIDDEN1_SIZE = 12
HIDDEN2_SIZE = 8
CLASSES = 10
if __name__ == '__main__':
    mode = sys.argv[1]

    train_x, train_y, test_x, test_y = util.mnist('../dataset/MNIST')

    if mode == 'train':
        w, b = train(train_x, train_y, test_x,
                     test_y, TOTAL_EPOCHES, BATCH_SIZE)
        # w, b = train(train_x[:100], train_y[:100], test_x[:100],
        #              test_y[:100], TOTAL_EPOCHES, BATCH_SIZE)
    elif mode == 'eval':
        # inference_after_building_model(test_x, test_y)
        inference_without_building_model(test_x, test_y)
    else:
        print('Usage: ./{} train|eval'.format(sys.argv[0]))
