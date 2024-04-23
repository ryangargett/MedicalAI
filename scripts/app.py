import torch
import re
import os
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig, pipeline
from langchain_community.llms.huggingface_pipeline import HuggingFacePipeline
from langchain_core.prompts import PromptTemplate
from langchain.chains import LLMChain
import numpy as np
from sentence_transformers import SentenceTransformer, util


def _get_bnb_config():

    config = BitsAndBytesConfig(
        load_in_8bit=True,
        bnb_4bit_compute_dtype=torch.float32
    )

    return config


def get_model_tokenizer(model_id):

    model_config = _get_bnb_config()

    model = AutoModelForCausalLM.from_pretrained(model_id,
                                                 device_map="auto",
                                                 quantization_config=model_config,)

    tokenizer = AutoTokenizer.from_pretrained(model_id,
                                              add_bos_token=True)

    if not os.path.exists(model_id):
        os.makedirs(model_id)

        model.save_pretrained(model_id, safe_serialization=False)
        tokenizer.save_pretrained(model_id)

    return tokenizer, model


def _get_diagnoses(diagnoses):

    message_components = diagnoses.split("Diagnoses:")

    if len(message_components) > 1:
        output = "Diagnoses:".join(message_components[1:])
    else:
        output = message_components[1]

    diagnoses = re.split(r"\d+\.", output)
    diagnoses = [diagnosis.strip().split('\n')[0] for diagnosis in diagnoses]  # Account for any unnecessary generation

    return diagnoses[1:]


def compute_similarity(ground_truth, diagnosis, em_extractor):

    em1 = em_extractor.encode(ground_truth, convert_to_tensor=True)
    em2 = em_extractor.encode(diagnosis, convert_to_tensor=True)

    cosine_similarity = util.cos_sim(em1, em2)
    return cosine_similarity.item()


def get_model_benchmark(diagnoses, ground_truth="Pulmonary histoplasmosis"):

    diagnoses = _get_diagnoses(diagnoses)

    print(f"Ground Truth: {ground_truth}")

    metrics = []

    embedding_extractor = SentenceTransformer("NeuML/pubmedbert-base-embeddings",
                                              device="cuda")

    for diagnosis in diagnoses:
        metric = compute_similarity(ground_truth, diagnosis, embedding_extractor)
        print(f"Diagnosis: {diagnosis}; Metric: {metric}")
        metrics.append(metric)

    weights = 1 / np.arange(1, len(metrics) + 1)

    weighted_similarity = np.average(metrics, weights=weights)
    return weighted_similarity


if __name__ == "__main__":
    # tokenizer_biom, model_biom = get_model_tokenizer("BioMistral/BioMistral-7B")
    tokenizer_meditron, model_meditron = get_model_tokenizer("epfl-llm/meditron-7b")

    pipe_meditron = pipeline("text-generation",
                             model=model_meditron,
                             tokenizer=tokenizer_meditron,
                             max_new_tokens=50,
                             temperature=0.1,
                             do_sample=True)

    hf_pipeline_meditron = HuggingFacePipeline(pipeline=pipe_meditron)

    template = "{system_prompt}\n\nCase: {case}\n\nQuery: {query}\n\nDiagnoses:"

    prompt = PromptTemplate(input_variables=["system_prompt", "case", "query"],
                            template=template)

    system_prompt = "You are a helpful medical assistant. You will be provided and asked about a complicated clinical case; read it carefully and then provide a concise DDx."
    query = "Provide five concise diagnoses. These should be sorted by likelihood."

    chain = LLMChain(llm=hf_pipeline_meditron,
                     prompt=prompt)

    get_output(chain, case)

    diagnosis = chain.run(system_prompt=system_prompt,
                          case=case,
                          query=query)

    metric = get_model_benchmark(diagnosis)
