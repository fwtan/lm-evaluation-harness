"""
Get To The Point: Summarization with Pointer-Generator Networks
https://arxiv.org/abs/1704.04368

The CNN / DailyMail Dataset is an English-language dataset containing just over 300k unique news articles 
as written by journalists at CNN and the Daily Mail. The current version supports both extractive and 
abstractive summarization, though the original version was created for machine reading and comprehension 
and abstractive question answering.

Homepage: https://github.com/abisee/cnn-dailymail
"""
from lm_eval.base import rf, Task
from lm_eval.metrics import mean
from transformers import AutoTokenizer
from rouge_score import rouge_scorer, scoring


_CITATION = """
@inproceedings{see-etal-2017-get,
    title = "Get To The Point: Summarization with Pointer-Generator Networks",
    author = "See, Abigail  and Liu, Peter J.  and Manning, Christopher D.",
    booktitle = "Proceedings of the 55th Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers)",
    month = jul,
    year = "2017",
    address = "Vancouver, Canada",
    publisher = "Association for Computational Linguistics",
    url = "https://www.aclweb.org/anthology/P17-1099",
    doi = "10.18653/v1/P17-1099",
    pages = "1073--1083",
}
"""


# Copied from https://github.com/EleutherAI/lm-evaluation-harness/blob/3ccea2b2854dd3cc9ff5ef1772e33de21168c305/lm_eval/tasks/scrolls.py#L125
def _num_cpu_cores():
    # https://stackoverflow.com/questions/1006289/how-to-find-out-the-number-of-cpus-using-python/55423170#55423170
    try:
        import psutil

        return psutil.cpu_count(logical=False)
    except ImportError:
        import os

        return len(os.sched_getaffinity(0))


class CNN_DailyMail(Task):
    VERSION = 0
    DATASET_PATH = "cnn_dailymail"
    DATASET_NAME = "3.0.0"

    PRUNE_TOKENIZERS = None
    PRUNE_MAX_TOKENS = None
    PRUNE_NUM_PROC = None

    def has_training_docs(self):
        return True

    def has_validation_docs(self):
        return True

    def has_test_docs(self):
        return True

    def training_docs(self):
        for doc in self.dataset["train"]:
            answer = doc["highlights"].strip()
            if answer[-1] != ".":
                doc["highlights"] = answer + "."
            else:
                doc["highlights"] = answer
            yield from self._process_doc(doc)

    def validation_docs(self):
        for doc in self.dataset["validation"]:
            answer = doc["highlights"].strip()
            if answer[-1] != ".":
                doc["highlights"] = answer + "."
            else:
                doc["highlights"] = answer
            yield from self._process_doc(doc)

    def test_docs(self):
        for doc in self.dataset["test"]:
            answer = doc["highlights"].strip()
            if answer[-1] != ".":
                doc["highlights"] = answer + "."
            else:
                doc["highlights"] = answer
            yield from self._process_doc(doc)

    def _process_doc(self, doc):
        doc["article"] = doc["article"].strip()
        doc["highlights"] = doc["highlights"].strip()
        return [doc]

    def doc_to_text(self, doc):
        return f"{doc['article']}\n\nQuestion: What is a summary of the preceding text?\nAnswer:"

    def doc_to_target(self, doc):
        # The prepended `" "` is required to space out the `doc_to_text` and
        # `doc_to_target` strings.
        target = doc["highlights"]
        return " " + target

    def construct_requests(self, doc, ctx):
        """Uses RequestFactory to construct Requests and returns an iterable of
        Requests which will be sent to the LM.

        :param doc:
            The document as returned from training_docs, validation_docs, or
            test_docs.
        :param ctx: str
            The context string, generated by fewshot_context. This includes the natural
            language description, as well as the few shot examples, and the question
            part of the document for `doc`.
        """
        return [rf.greedy_until(ctx, {"until": ["."]})]

    def rouge(self, refs, preds):
        """
        Returns `t5` style ROUGE scores. See the related implementation:
        https://github.com/google-research/text-to-text-transfer-transformer/blob/3d10afd51ba97ac29eb66ae701eca274488202f7/t5/evaluation/metrics.py#L68

        :param refs:
            A `list` of reference `strs`.
        :param preds:
            A `list` of predicted `strs`.
        """
        rouge_types = ["rouge1", "rouge2", "rougeLsum"]
        scorer = rouge_scorer.RougeScorer(rouge_types)
        # Add newlines between sentences to correctly compute `rougeLsum`.

        def _prepare_summary(summary):
            summary = summary.replace(" . ", ".\n")
            return summary

        # Accumulate confidence intervals.
        aggregator = scoring.BootstrapAggregator()
        for ref, pred in zip(refs, preds):
            ref = _prepare_summary(ref)
            pred = _prepare_summary(pred)
            aggregator.add_scores(scorer.score(ref, pred))
        result = aggregator.aggregate()
        return {type: result[type].mid.fmeasure * 100 for type in rouge_types}

    def process_results(self, doc, results):
        """Take a single document and the LM results and evaluates, returning a
        dict where keys are the names of submetrics and values are the values of
        the metric for that one document

        :param doc:
            The document as returned from training_docs, validation_docs, or test_docs.
        :param results:
            The results of the requests created in construct_requests.
        """
        completion = results[0].strip()
        ref = doc["highlights"]
        # ROUGE-N
        rouge_score = self.rouge([ref], [completion])
        # ROUGE-1
        rouge1 = rouge_score["rouge1"]
        # ROUGE-2
        rouge2 = rouge_score["rouge2"]
        # ROUGE-L
        rougeL = rouge_score["rougeLsum"]
        return {
            "rouge1": rouge1,
            "rouge2": rouge2,
            "rougeL": rougeL,
        }

    def aggregation(self):
        """
        :returns: {str: [metric_score] -> float}
            A dictionary where keys are the names of submetrics and values are
            functions that aggregate a list of metric scores
        """
        return {
            "rouge1": mean,
            "rouge2": mean,
            "rougeL": mean,
        }

    def higher_is_better(self):
        return {
            "rouge1": True,
            "rouge2": True,
            "rougeL": True,
        }

    
    #####################################################################################
    ## Adapted from https://github.com/EleutherAI/lm-evaluation-harness/blob/master/lm_eval/tasks/scrolls.py
    def download(self, *args, **kwargs):
        super().download(*args, **kwargs)
        if self.PRUNE_TOKENIZERS is not None and self.PRUNE_TOKENIZERS is not None:
            self.prune()

    def _get_prune_text(self, sample):
        return self.doc_to_text(self._process_doc(sample)[0])

    def prune(self):
        """Create a pruned version of a SCROLLS task dataset containing only inputs
        that are less than `max_tokens` when tokenized by each tokenizer
        """

        tokenizers = [
            AutoTokenizer.from_pretrained(tokenizer)
            for tokenizer in self.PRUNE_TOKENIZERS
        ]
        cache = {}

        def _filter(sample):
            text = self._get_prune_text(sample)
            cached = cache.get(text, None)
            if cached is None:
                for tokenizer in tokenizers:
                    if len(tokenizer(text).input_ids) > self.PRUNE_MAX_TOKENS:
                        cache[text] = False
                        return False
                cache[text] = True
                return True
            else:
                return cached

        self.dataset = self.dataset.filter(_filter, num_proc=self.PRUNE_NUM_PROC)


class CNN_DailyMail_Short(CNN_DailyMail):
    PRUNE_TOKENIZERS = ["PY007/TinyLlama-1.1B-Chat-v0.3"]
    PRUNE_MAX_TOKENS = 1280
    PRUNE_NUM_PROC = _num_cpu_cores() # optional, to speed up pruning of large datasets like NarrativeQA