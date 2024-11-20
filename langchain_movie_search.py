import os
from dotenv import load_dotenv
import pymongo
from langchain_huggingface import HuggingFaceEndpoint, HuggingFaceEmbeddings
from langchain_mongodb.vectorstores import MongoDBAtlasVectorSearch
from langchain.chains import create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate
import gradio as gr
from gradio.themes.base import Base
from flask import Flask

__author__ = "Chirag Kamble"


# Flask App
app = Flask(__name__)


class MoviesSearch:
    """
    Class to perform Vector Index Search using MongoDB and LLM search using Langchain on Movies
    """

    def __init__(self):
        """
        Initializing method
        """
        # Load environment variables
        load_dotenv()
        transformer_model_name: str = os.getenv("TRANSFORMER_MODEL_NAME")
        mongodb_connection_url: str = os.getenv("MONGODB_CONNECTION_URL")
        mongodb_db_name: str = os.getenv("MONGODB_DB_NAME")
        mongodb_collection_name: str = os.getenv("MONGODB_COLLECTION_NAME")
        self.huggingface_repo: str = os.getenv("HF_REPO")
        self.huggingface_api_token: str = os.getenv("HF_TOKEN")
        self.huggingface_text_generation_model: str = os.getenv("HUGGINGFACE_TEXT_GENERATION_MODEL")

        # Setup MongoDB connection
        self.client: pymongo.synchronous.mongo_client.MongoClient = pymongo.MongoClient(mongodb_connection_url)
        db: str = mongodb_db_name
        collection_name: str = mongodb_collection_name
        self.langchain_movies_collection: pymongo.synchronous.collection.Collection = self.client[db][collection_name]

        self.sample_movies_collection: pymongo.synchronous.collection.Collection = self.client.sample_mflix.movies

        self.hf_plot_embedding = HuggingFaceEmbeddings(
            model_name=transformer_model_name,
            show_progress=True,
        )

        self.retrieve_vector_store = MongoDBAtlasVectorSearch(collection=self.langchain_movies_collection,
                                                              embedding=self.hf_plot_embedding,
                                                              embedding_key="embedding",
                                                              index_name="langchain_movies_vector_index",
                                                              text_key="text",
                                                              )

    def generate_insert_embeddings(self):
        """
        Generate vector embeddings
        """
        new_doc_list: List[Document] = []
        for doc in self.sample_movies_collection.find({"plot": {"$exists": True}}).limit(9000):
            new_doc: Document = Document(
                page_content=doc["plot"],
                metadata={"source": "Collection sample_mflix",
                          "movie-title": doc["title"],
                          "movie-plot": doc["plot"],
                          "text": doc["plot"]}
            )
            new_doc_list.append(new_doc)
        self.retrieve_vector_store.from_documents(
            documents=new_doc_list,
            embedding=self.hf_plot_embedding,
            collection=self.langchain_movies_collection
        )

    def query_data(self, query: str):
        """
        Query data from Atlas Vector Search
        :param query: A user query to search
        :return: String answer generated by the LLM
        """
        hf_llm: HuggingFaceEndpoint = HuggingFaceEndpoint(
            repo_id=self.huggingface_text_generation_model,
            huggingfacehub_api_token=self.huggingface_api_token,
            # temperature=0.1,
            task="text-generation",
            # max_new_tokens=512,
            verbose=True,
            return_full_text=True,
        )

        retriever = self.retrieve_vector_store.as_retriever()
        prompt = PromptTemplate.from_template(template="{context}",
                                              template_format="f-string")
        combine_docs = create_stuff_documents_chain(llm=hf_llm, prompt=prompt, )

        retrival_chain = create_retrieval_chain(retriever=retriever, combine_docs_chain=combine_docs)
        hf_llm_retriver_output = retrival_chain.invoke({"input": query})

        llm_answer = hf_llm_retriver_output.get("answer")

        return llm_answer

    def run_website(self):
        with gr.Blocks(theme=Base(), title="Movie plot search App using Vector Search + RAG") as v_search:
            gr.Markdown("Movie plot search App using Vector Search + RAG")
            textbox = gr.Textbox(label="Enter your question:", lines=1)
            with gr.Row():
                button = gr.Button("Submit", variant="primary")
            with gr.Column():
                output = gr.Textbox(lines=1, max_lines=10, interactive=False,
                                    label="""Output generated by chaining Atlas Vector Search with Langchain's RAG""",)

            button.click(fn=self.query_data, inputs=textbox, outputs=[output])

        v_search.launch(share=True)

    def close_client(self):
        self.client.close()


@app.route("/", methods=["GET"])
def gradio_interface():
    movie_search = MoviesSearch()
    movie_search.run_website()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=os.getenv("PORT", "5000"), debug=True)
