import streamlit as st # Import python packages
cnx = st.connection("snowflake")
session = cnx.session()

import pandas as pd

pd.set_option("max_colwidth",None)

### Default Values
#model_name = 'mistral-7b' #Default but we allow user to select one
num_chunks = 3 # Num-chunks provided as context. Play with this to check how it affects your accuracy
slide_window = 7 # how many last conversations to remember. This is the slide window.
#debug = 1 #Set this to 1 if you want to see what is the text created as summary and sent to get chunks
#use_chat_history = 0 #Use the chat history by default

### Functions

def main():
    
    st.title(f":speech_balloon: ChatBot Snowflake Cortex")
    st.write("Lista de documentos disponibles:")
    docs_available = session.sql("ls @docs").collect()
    list_docs = []
    for doc in docs_available:
        list_docs.append(doc["name"])
    st.dataframe(list_docs)

    config_options()
    init_messages()
     
    # Display chat messages from history on app rerun
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    
    # Accept user input
    if question := st.chat_input("Que deseas saber?"):
        # Add user message to chat history
        st.session_state.messages.append({"role": "user", "content": question})
        # Display user message in chat message container
        with st.chat_message("user"):
            st.markdown(question)
        # Display assistant response in chat message container
        with st.chat_message("assistant"):
            message_placeholder = st.empty()
    
            question = question.replace("'","")
    
            with st.spinner(f"{st.session_state.model_name} Pensando..."):
                response = complete(question)
                res_text = response[0].RESPONSE     
            
                res_text = res_text.replace("'", "")
                message_placeholder.markdown(res_text)
        
        st.session_state.messages.append({"role": "assistant", "content": res_text})


def config_options():


    
    st.sidebar.selectbox('Selecciona el Modelo a ocupar:',(
                                    'mixtral-8x7b',
                                    'snowflake-arctic',
                                    'mistral-large',
                                    'llama3-8b',
                                    'llama3-70b',
                                    'reka-flash',
                                     'mistral-7b',
                                     'llama2-70b-chat',
                                     'gemma-7b'), key="model_name")
                                           
    # For educational purposes. Users can chech the difference when using memory or not
    st.sidebar.checkbox('Recordar Historial del Chat?', key="use_chat_history", value = True)

    st.sidebar.checkbox('Debug: Ver el resumen generado de la conversación anterior.', key="debug", value = True)
    st.sidebar.button("Empezar de nuevo", key="clear_conversation")
    st.sidebar.expander("Session State").write(st.session_state)


def init_messages():

    # Initialize chat history
    if st.session_state.clear_conversation or "messages" not in st.session_state:
        st.session_state.messages = []

    
def get_similar_chunks (question):

    cmd = """
        with results as
        (SELECT RELATIVE_PATH,
           VECTOR_COSINE_SIMILARITY(docs_chunks_table.chunk_vec,
                    SNOWFLAKE.CORTEX.EMBED_TEXT_768('e5-base-v2', ?)) as similarity,
           chunk
        from docs_chunks_table
        order by similarity desc
        limit ?)
        select chunk, relative_path from results 
    """
    
    df_chunks = session.sql(cmd, params=[question, num_chunks]).to_pandas()       

    df_chunks_lenght = len(df_chunks) -1

    similar_chunks = ""
    for i in range (0, df_chunks_lenght):
        similar_chunks += df_chunks._get_value(i, 'CHUNK')

    similar_chunks = similar_chunks.replace("'", "")
             
    return similar_chunks


def get_chat_history():
#Get the history from the st.session_stage.messages according to the slide window parameter
    
    chat_history = []
    
    start_index = max(0, len(st.session_state.messages) - slide_window)
    for i in range (start_index , len(st.session_state.messages) -1):
         chat_history.append(st.session_state.messages[i])

    return chat_history

    
def summarize_question_with_history(chat_history, question):
# To get the right context, use the LLM to first summarize the previous conversation
# This will be used to get embeddings and find similar chunks in the docs for context

    prompt = f"""
        Based on the chat history below and the question, generate a query that extend the question
        with the chat history provided. The query should be in natual language. 
        Answer with only the query. Do not add any explanation.
        
        <chat_history>
        {chat_history}
        </chat_history>
        <question>
        {question}
        </question>
        """
    
    cmd = """
            select snowflake.cortex.complete(?, ?) as response
          """
    df_response = session.sql(cmd, params=[st.session_state.model_name, prompt]).collect()
    sumary = df_response[0].RESPONSE     

    if st.session_state.debug:
        st.sidebar.text("Summary to be used to find similar chunks in the docs:")
        st.sidebar.caption(sumary)

    sumary = sumary.replace("'", "")

    return sumary

def create_prompt (myquestion):

    if st.session_state.use_chat_history:
        chat_history = get_chat_history()

        if chat_history != []: #There is chat_history, so not first question
            question_summary = summarize_question_with_history(chat_history, myquestion)
            prompt_context =  get_similar_chunks(question_summary)
        else:
            prompt_context = get_similar_chunks(myquestion) #First question when using history
    else:
        prompt_context = get_similar_chunks(myquestion)
        chat_history = ""
  
    prompt = f"""
           You are an expert chat assistance that extracs information from the CONTEXT provided
           between <context> and </context> tags.
           You offer a chat experience considering the information included in the CHAT HISTORY
           provided between <chat_history> and </chat_history> tags..
           When ansering the question contained between <question> and </question> tags
           be concise and do not hallucinate. 
           Speak in Spanish.
           If you don´t have the information just say so.
           
           Do not mention the CONTEXT used in your answer.
           Do not mention the CHAT HISTORY used in your asnwer.
           
           <chat_history>
           {chat_history}
           </chat_history>
           <context>          
           {prompt_context}
           </context>
           <question>  
           {myquestion}
           </question>
           Answer: 
           """

    return prompt


def complete(myquestion):

    prompt =create_prompt (myquestion)
    cmd = """
            select snowflake.cortex.complete(?, ?) as response
          """
    
    df_response = session.sql(cmd, params=[st.session_state.model_name, prompt]).collect()
    return df_response

if __name__ == "__main__":
    main()
