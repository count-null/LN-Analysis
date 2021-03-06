###
# helpers.py
#
# Helper functions for use in this project
#
# Usage: from helpers import *
###

from shutil import which
import subprocess
import yaml
import json
import glob
import math
import sys
import os.path
from os.path import join
import pickle
from datetime import datetime
import networkx as nx
from bs4 import BeautifulSoup as bs
import requests
from many_requests import ManyRequests
from pathlib import Path
from copy import deepcopy
from networkx.classes import graph as nx_Graph
import pickle
from lnsimulator.ln_utils import load_temp_data, generate_directed_graph
from random import randint
import time
import pandas as pd
from scipy.stats import percentileofscore
import lnsimulator.simulator.transaction_simulator as ts

configPath = "./config.yml"


def getConfig():
    if not os.path.isfile(configPath):
        print(
            "%s does not exist. Copy example.config.yml to this path and edit with your configuration.\n\n    E.x. cp example.config.yml %s\n" % (
                configPath, configPath))
        return False
    with open(configPath) as f:
        return yaml.load(f, Loader=yaml.FullLoader)

def millify(n):
    n = float(n)
    millnames = ['','K','M','B','T']
    millidx = max(0,min(len(millnames)-1, int(math.floor(0 if n ==0 else math.log10(abs(n))/3))))
    return '{:.0f}{}'.format(n/10**(3*millidx), millnames[millidx])


def sh(command):
    subprocess.call(command.split(' '))


def grab(command):
    return str(subprocess.check_output(command.split(' ')), 'utf-8')


def isCommand(name):
    """Check whether `name` is on PATH and marked as executable."""
    return which(name) is not None


def getDict(f):
    with open(f, "rb") as j:
        return (json.load(j, encoding='utf-32'), Path(f).stem)


def getGraph(f):
    # Create an empty graph
    graphJson, name = getDict(f)
    # TODO name graph based on timestamp - from filename
    G = nx.Graph(name=name)
    if graphJson.get("graph", None):
        graphJson = graphJson["graph"]
    # Parse and add nodes
    for node in graphJson['nodes']:
        if node.get('last_update', 0) == 0:
            continue
        G.add_node(
            node['pub_key'],
            alias=node['alias'],
            addresses=node['addresses'],
            color=node['color'],
            last_update=node['last_update']
        )

    # Parse and add edges
    for edge in graphJson['edges']:
        if edge['last_update'] == 0:
            continue
        if edge['node1_policy'] is None or edge['node2_policy'] is None:
            continue
        if edge['node1_policy']['disabled'] is None or edge['node2_policy']['disabled'] is None:
            continue
        G.add_edge(
            edge['node1_pub'],
            edge['node2_pub'],
            # weight=1,
            channel_id=edge['channel_id'],
            chan_point=edge['chan_point'],
            last_update=edge['last_update'],
            capacity=edge['capacity'],
            node1_policy=edge['node1_policy'],
            node2_policy=edge['node2_policy']
        )
    G.remove_nodes_from([x for x in G.nodes() if G.degree[x] == 0])

    return G


def remove_subs(G):
    """
    Removes all subgraphs besides the largest one.
    """
    components = list(nx.connected_components(G))
    mainnet = max(components, key=len)
    components.remove(mainnet)
    for component in components:
        G.remove_nodes_from(component)
    return G


def clean_graph(graph, save=True):
    # take NetworkX Graph as input
    articulation_points = list(nx.articulation_points(graph))
    # remove articulation points, then remove components, then add back in articulation points
    graph_copy = deepcopy(graph)  # because adding back the articulation points does not add back the edges
    graph_copy.remove_nodes_from(articulation_points)
    components = list(nx.connected_components(graph_copy))
    mainnet = max(components, key=len)
    kept_nodes = mainnet | set(articulation_points)
    removed_nodes = set(graph.nodes()) - kept_nodes
    graph.remove_nodes_from(removed_nodes)
    graph = remove_subs(graph)

    # save graph in cleaned_graphs dir
    if save:
        config = getConfig()
        save_graph(graph, loc=config["clean_dir"])
    return graph


def save_graph(graph, loc):
    graph_data = nx.readwrite.node_link_data(graph, {"name": "pub_key",
                                                     "link": "edges",
                                                     "source": "node1_pub",
                                                     "target": "node2_pub"})
    graph_data = {"graph": graph_data, "timestamp": graph.name}
    del graph_data["graph"]["directed"]
    del graph_data["graph"]["multigraph"]
    del graph_data["graph"]["graph"]
    mkdir(loc)
    with open(join(loc, str(graph.name) + '-graph.json'), 'w') as outfile:
        json.dump(graph_data, outfile)


def mkdir(d):
    """Makes a directory if it does not exist"""
    Path(d).mkdir(exist_ok=True)

def get_arguments(get):
    args = []
    i = 1
    for var in get:
        if get[var][0]:
            args.append(sys.argv[i])
        else:
            args.append(get[var][1]())
        i+=1
    return args

def graphSelector():
    graphs = glob.glob("../../_graphs/*")
    if len(graphs) == 0:
        print(
                "No graphs found in _graphs.\n\nlncli describegraph > graph.json\n\nTip: use the scripts in snapshots/ to automate graph collection. Exiting.")
        return False
    if len(graphs) == 1:
        return graphs[0]
    else:
        print("Showing all archived graph json:\n")
        for i, graph in enumerate(graphs):
            file = graph.split("/")[-1].lstrip("//graphs\\")
            print("%s - %s" % (i, file))
        choice = input("\nPlease select a snapshot. Enter a number 0-%s: " % (len(graphs) - 1))
        return graphs[int(choice)]


def get_merchant_data():
    # go to directory
    # grab all categories
    # go to all categories
    # grab all pub keys on each page
    # get json data of each merchant
    # return a list of merchant data

    if os.path.isfile("merchants.json"):
        print("Merchants json found, delete it to update.")
        with open("merchants.json", "r") as fileobj:
            merchant_dict = json.load(fileobj)
    else:
        print("Merchants json updating...")
        base_url = "https://1ml.com"
        directory_link = join(base_url, "directory")
        response = requests.get(directory_link)
        directory_soup = bs(response.content, "html.parser")
        categories = directory_soup.find_all("li", {"class": "list-group-item"})[1:]
        links = []

        for category in categories:
            links.extend(category.find_all("a", {"title": True}))
        links = [link["href"] for link in links]
        print(links)
        links = [base_url + link for link in links]  # idk why join doesnt work here
        print(links)

        responses = ManyRequests(n_workers=10, n_connections=10)(
            method='GET', url=links)

        pub_keys = []
        for response in responses:
            soup = bs(response.content, "html.parser")
            pub_keys.extend(soup.find_all("strong", {"class": "small selectable"}))

        pub_keys = list(set([pub_key.text for pub_key in pub_keys]))

        merchant_data = get_1ml_data(pub_keys)
        merchant_dict = convert_data(merchant_data)

        with open("merchants.json", "w") as fileobj:
            json.dump(merchant_dict, fileobj)
    return merchant_dict


def get_1ml_data(pubkeys: list) -> list:
    base_url = "https://1ml.com/node/{}/json"
    urls = [base_url.format(pubkey) for pubkey in pubkeys]
    all_json = []
    responses = ManyRequests(n_workers=20, n_connections=20)(
        method='GET', url=urls)
    for response in responses:
        son = response.json()
        all_json.append(son)
    return all_json


def convert_data(merchant_data: list) -> dict:
    # map each element in the list to its pubkey and return the resulting dict
    merchant_dict = {}
    for merchant in merchant_data:
        pubkey = merchant["pub_key"]
        merchant.pop("pub_key", None)
        merchant_dict[pubkey] = merchant
    return merchant_dict


def save_load_betweenness_centralities(base_graph: nx_Graph) -> dict:
    """
    If there exists a file titled ./btwn/<timestamp>.pickle, load and return it
    else, find all shortest path lengths for a given graph, save and return the information
    """
    btwn_dir = "btwn"
    Path(btwn_dir).mkdir(exist_ok=True)
    filename = join(btwn_dir, "{}.pickle".format(base_graph.name))
    if os.path.isfile(filename):
        print("Using cached betweenness centrality from " + filename)
        with open(filename, "rb") as f:
            btwn_dict = pickle.load(f)
    else:
        print("Calculating betweenness centrality for " + base_graph.name )
        btwn_dict = dict(nx.betweenness_centrality(base_graph))
        print("Saving result in " + filename)
        with open(filename, "wb") as f:
            pickle.dump(btwn_dict, f)
    return btwn_dict


def save_load_closeness_centralities(base_graph: nx_Graph) -> dict:
    """
    If there exists a file titled ./close/<timestamp>.pickle, load and return it
    else, find all shortest path lengths for a given graph, save and return the information
    """
    close_dir = "close"
    Path(close_dir).mkdir(exist_ok=True)
    filename = join(close_dir, "{}.pickle".format(base_graph.name))
    if os.path.isfile(filename):
        print("Using cached closeness centrality from " + filename)
        with open(filename, "rb") as f:
            close_dict = pickle.load(f)
    else:
        print("Calculating closeness centrality for " + base_graph.name)
        close_dict = dict(nx.closeness_centrality(base_graph))
        print("Saving result in " + filename)
        with open(filename, "wb") as f:
            pickle.dump(close_dict, f)
    return close_dict


def make_edges_from_template(node_id, nbr_ids):
    edges = []
    for nbr_id in nbr_ids:
        edge = {
            "channel_id": randint(799999999999999999, 999999999999999999),
            "last_update": time.time(),
            "capacity": 1000000,
            "node1_policy": {
                "time_lock_delta": 100,
                "min_htlc": 1000,
                "fee_base_msat": 1000,
                "fee_rate_milli_msat": 1,
                "disabled": False,
            },
            "node2_policy": {
                "time_lock_delta": 100,
                "min_htlc": 1000,
                "fee_base_msat": 1000,
                "fee_rate_milli_msat": 1,
                "disabled": False,
            },
            "node1_pub": node_id,
            "node2_pub": nbr_id,
        }
        edges.append(edge)
    return edges


def make_node_from_template(node_id):
    node = {
        "pub_key": node_id,
        "last_update": time.time()
    }
    return node


def preprocess_json_file(json_file, additional_node, additional_edges):
    """Generate directed graph data (traffic simulator input format) from json LN snapshot file."""
    json_files = [json_file]
    # print("\ni.) Load data")
    node_keys = ["pub_key", "last_update"],
    EDGE_KEYS = ["node1_pub", "node2_pub", "last_update", "capacity", "channel_id", 'node1_policy', 'node2_policy']
    nodes, edges = load_temp_data(json_files, edge_keys=EDGE_KEYS)
    # print(len(nodes), len(edges))

    # add candidate nodes
    pd_add_node = pd.DataFrame([additional_node])
    pd_add_edges = pd.DataFrame(additional_edges)
    edges = pd.concat([edges, pd_add_edges])
    # nodes = pd.concat([nodes, pd_add_node])
    edges = edges.reset_index(drop=True)
    # nodes = nodes.reset_index(drop=True)
    # print(len(nodes), len(edges))

    # print("Remove records with missing node policy")
    # print(edges.isnull().sum() / len(edges))
    origi_size = len(edges)
    edges = edges[(~edges["node1_policy"].isnull()) & (~edges["node2_policy"].isnull())]
    # print(origi_size - len(edges))
    # print("\nii.) Transform undirected graph into directed graph")
    directed_df = generate_directed_graph(edges)
    # print(directed_df.head())
    # print("\niii.) Fill missing policy values with most frequent values")
    # print("missing values for columns:")
    # print(directed_df.isnull().sum())
    directed_df = directed_df.fillna(
        {"disabled": False, "fee_base_msat": 1000, "fee_rate_milli_msat": 1, "min_htlc": 1000})
    for col in ["fee_base_msat", "fee_rate_milli_msat", "min_htlc"]:
        directed_df[col] = directed_df[col].astype("float64")
    return directed_df


def normalize_dicts(_dict):
    # closeness_dict
    ckeys, cvalues = list(_dict.keys()), list(_dict.values())
    # we want to maximize closeness
    percentiles = [(percentileofscore(cvalues, value, "rank")) / 100 for value in cvalues]
    return dict(zip(ckeys, percentiles))


def eval_recommendation(base_graph, edge_ids, node_id):
    new_edges = make_edges_from_template(node_id, edge_ids)
    new_node = make_node_from_template(node_id)
    directed_edges = preprocess_json_file(base_graph, new_node, new_edges)
    merchant_data = get_merchant_data()
    merchant_keys = list(merchant_data.keys())

    # SIMULATOR PARAMS
    transaction_size = 12000
    num_transactions = 8000  # (~.96 bitcoin rough estimate of the amount transacted per day )
    epsilon = 0.8
    drop_disabled = True
    drop_low_cap = False
    with_depletion = True

    simulator = ts.TransactionSimulator(directed_edges,
                                        merchant_keys,
                                        transaction_size,
                                        num_transactions,
                                        drop_disabled=drop_disabled,
                                        drop_low_cap=drop_low_cap,
                                        epsilon=epsilon,
                                        with_depletion=with_depletion
                                        )
    cheapest_paths, _, all_router_fees, _ = simulator.simulate(weight="total_fee",
                                                               max_threads=16,
                                                               with_node_removals=False)
    node_stats = all_router_fees.groupby("node")["fee"].sum().get(node_id, 0)  # return 0 if node did not make any fees
    top_5_stats = all_router_fees.groupby("node")["fee"].sum().sort_values(ascending=False).head(10)
    median = all_router_fees.groupby("node")["fee"].sum().median()
    print("Top 10 earners:")
    print(top_5_stats)
    print("Median")  # 50% of nodes make less than this amount per day
    print(median)
    print("Us:")
    print(node_stats)
