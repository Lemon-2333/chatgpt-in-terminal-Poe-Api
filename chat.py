#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import json
import logging
import os
import sys
from datetime import datetime

import requests
from dotenv import load_dotenv
from prompt_toolkit import PromptSession, prompt
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.markdown import Markdown

# 日志记录到 chat.log，注释下面这行可不记录日志
logging.basicConfig(filename=f'{sys.path[0]}/chat.log', format='%(asctime)s %(name)s: %(levelname)-6s %(message)s',
                    datefmt='[%Y-%m-%d %H:%M:%S]', level=logging.INFO, encoding="UTF-8")
log = logging.getLogger("chat")

console = Console()

style = Style.from_dict({
    "prompt": "ansigreen",  # 将提示符设置为绿色
})


class ChatSettings:
    def __init__(self, timeout: int):
        self.raw_mode = False
        self.multi_line_mode = False
        self.timeout = timeout

    def toggle_raw_mode(self):
        self.raw_mode = not self.raw_mode
        console.print(
            f"[dim]Raw mode {'enabled' if self.raw_mode else 'disabled'}, use `/last` to display the last answer.")

    def toggle_multi_line_mode(self):
        self.multi_line_mode = not self.multi_line_mode
        if self.multi_line_mode:
            console.print(
                f"[dim]Multi-line mode enabled, press [[bright_magenta]Esc[/]] + [[bright_magenta]ENTER[/]] to submit.")
        else:
            console.print(f"[dim]Multi-line mode disabled.")
    
    def set_timeout(self, timeout):
        try:
            self.timeout = float(timeout)
        except ValueError:
            console.print("[red]Input must be a number")
            return
        console.print(f"[dim]API timeout set to [green]{timeout}s[/].")


class CHATGPT:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.endpoint = "https://api.openai.com/v1/chat/completions"
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        self.messages = [
            {"role": "system", "content": "You are a helpful assistant."}]
        self.total_tokens = 0
        self.current_tokens = 0

    def send(self, message: str, timeout: float):
        self.messages.append({"role": "user", "content": message})
        data = {
            "model": "gpt-3.5-turbo",
            "messages": self.messages
        }
        try:
            response = requests.post(self.endpoint, headers=self.headers, data=json.dumps(data), timeout=timeout)
            if response.status_code == 400:
                error_msg = response.json()['error']['message']
                self.messages.pop()
                console.print(f"[red]Error: {error_msg}")
                log.error(error_msg)
                return None
            else:
                response.raise_for_status()
        except KeyboardInterrupt:
            self.messages.pop()
            console.print("[bold cyan]Aborted.")
            raise
        except requests.exceptions.ReadTimeout as e:
            self.messages.pop()
            console.print(f"[red]Error: API read timed out ({timeout}s). You can retry or increase the timeout.", highlight=False)
            # log.exception(e)
            return None
        except requests.exceptions.RequestException as e:
            self.messages.pop()
            console.print(f"[red]Error: {str(e)}")
            log.exception(e)
            return None
        except Exception as e:
            self.messages.pop()
            console.print(
                f"[red]Error: {str(e)}. Check log for more information")
            log.exception(e)
            self.save_chat_history(
                f'{sys.path[0]}/chat_history_backup_{datetime.now().strftime("%Y-%m-%d_%H,%M,%S")}.json')
            raise EOFError
        response_json = response.json()
        log.debug(f"Response: {response_json}")
        self.current_tokens = response_json["usage"]["total_tokens"]
        self.total_tokens += self.current_tokens
        reply = response_json["choices"][0]["message"]
        self.messages.append(reply)
        return reply

    def save_chat_history(self, filename):
        with open(f"{filename}", 'w', encoding='utf-8') as f:
            json.dump(self.messages, f, ensure_ascii=False, indent=4)
        console.print(
            f"[dim]Chat history saved to: [bright_magenta]{filename}", highlight=False)

    def modify_system_prompt(self, new_content):
        if self.messages[0]['role'] == 'system':
            old_content = self.messages[0]['content']
            self.messages[0]['content'] = new_content
            console.print(
                f"[dim]System prompt has been modified from '{old_content}' to '{new_content}'.")
            if len(self.messages) > 1:
                console.print(
                    "[dim]Note this is not a new chat, modifications to the system prompt have limited impact on answers.")
        else:
            console.print(
                f"[dim]No system prompt found in messages.")


class CustomCompleter(Completer):
    commands = [
        '/raw', '/multi', '/tokens', '/last', '/save', '/system', '/timeout', '/undo', '/help', '/exit'
    ]

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if text.startswith('/'):
            for command in self.commands:
                if command.startswith(text):
                    yield Completion(command, start_position=-len(text))


def print_message(message, settings: ChatSettings):
    '''打印单条来自 ChatGPT 或用户的消息'''
    role = message["role"]
    content = message["content"]
    if role == "user":
        print(f"> {content}")
    elif role == "assistant":
        console.print("ChatGPT: ", end='', style="bold cyan")
        if settings.raw_mode:
            print(content)
        else:
            console.print(Markdown(content), new_line_start=True)


def handle_command(command: str, chatGPT: CHATGPT, settings: ChatSettings):
    '''处理斜杠(/)命令'''
    if command == '/raw':
        settings.toggle_raw_mode()
    elif command == '/multi':
        settings.toggle_multi_line_mode()

    elif command == '/tokens':
        console.print(
            f"[dim]Total tokens: {chatGPT.total_tokens}")
        console.print(
            f"[dim]Current tokens: {chatGPT.current_tokens}[/]/[black]4097")

    elif command == '/last':
        reply = chatGPT.messages[-1]
        print_message(reply, settings)

    elif command.startswith('/save'):
        args = command.split()
        if len(args) > 1:
            filename = args[1]
        else:
            date_filename = f'./chat_history_{datetime.now().strftime("%Y-%m-%d_%H,%M,%S")}.json'
            filename = prompt("Save to: ", default=date_filename, style=style)
        chatGPT.save_chat_history(filename)

    elif command.startswith('/system'):
        args = command.split()
        if len(args) > 1:
            new_content = ' '.join(args[1:])
        else:
            new_content = prompt(
                "System prompt: ", default=chatGPT.messages[0]['content'], style=style)
        if new_content != chatGPT.messages[0]['content']:
            chatGPT.modify_system_prompt(new_content)
        else:
            console.print("[dim]No cahnge.")

    elif command.startswith('/timeout'):
        args = command.split()
        if len(args) > 1:
            new_timeout = args[1]
        else:
            new_timeout = prompt(
                "Set OpenAI API timeout: ", default=str(settings.timeout), style=style)
        if new_timeout != str(settings.timeout):
            settings.set_timeout(new_timeout)
        else:
            console.print("[dim]No cahnge.")

    elif command == '/undo':
        if len(chatGPT.messages) > 2:
            answer = chatGPT.messages.pop()
            question = chatGPT.messages.pop()
            truncated_question = question['content'].split('\n')[0]
            if len(question['content']) > len(truncated_question):
                truncated_question += "..."
            console.print(
                f"[dim]Last question: '{truncated_question}' and it's answer has been removed.")
        else:
            console.print("[dim]Nothing to undo.")

    elif command == '/exit':
        raise EOFError

    else:
        console.print('''[bold]Available commands:[/]
    /raw                     - Toggle raw mode (showing raw text of ChatGPT's reply)
    /multi                   - Toggle multi-line mode (allow multi-line input)
    /tokens                  - Show total tokens and current tokens used
    /last                    - Display last ChatGPT's reply
    /save \[filename_or_path] - Save the chat history to a file
    /system \[new_prompt]     - Modify the system prompt
    /timeout \[new_timeout]   - Modify the api timeout
    /undo                    - Undo the last question and remove its answer
    /help                    - Show this help message
    /exit                    - Exit the application''')


def load_chat_history(file_path):
    '''从 file_path 加载聊天记录'''
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            chat_history = json.load(f)
        return chat_history
    except FileNotFoundError:
        console.print(f"[bright_red]File not found: {file_path}")
    except json.JSONDecodeError:
        console.print(f"[bright_red]Invalid JSON format in file: {file_path}")
    return None


def create_key_bindings(settings: ChatSettings):
    '''自定义回车事件绑定，实现斜杠命令的提交忽略多行模式'''
    key_bindings = KeyBindings()

    @key_bindings.add(Keys.Enter, eager=True)
    def _(event):
        buffer = event.current_buffer
        text = buffer.text.strip()
        if text.startswith('/') or not settings.multi_line_mode:
            buffer.validate_and_handle()
        else:
            buffer.insert_text('\n')

    return key_bindings


def main(args):
    # 从 .env 文件中读取 OPENAI_API_KEY
    load_dotenv()
    if args.key:
        api_key = os.environ.get(args.key)
    else:
        api_key = os.environ.get("OPENAI_API_KEY")
    # if 'key' arg triggered, load the api key from .env with the given key-name;
    # otherwise load the api key with the key-name "OPENAI_API_KEY"
    if not api_key:
        api_key = prompt("OpenAI API Key not found, please input: ")
    api_timeout = int(os.environ.get("OPENAI_API_TIMEOUT", "20"))

    chatGPT = CHATGPT(api_key)
    chat_settings = ChatSettings(api_timeout)

    # 绑定回车事件，达到自定义多行模式的效果
    key_bindings = create_key_bindings(chat_settings)

    try:
        console.print(
            "[dim]Hi, welcome to chat with GPT. Type `[bright_magenta]\help[/]` to display available commands.")

        if args.multi:
            chat_settings.toggle_multi_line_mode()

        if args.raw:
            chat_settings.toggle_raw_mode()

        if args.load:
            chat_history = load_chat_history(args.load)
            if chat_history:
                chatGPT.messages = chat_history
                for message in chatGPT.messages:
                    print_message(message, chat_settings)
                console.print(
                    f"[dim]Chat history successfully loaded from: [bright_magenta]{args.load}", highlight=False)

        session = PromptSession()

        # 自定义命令补全，保证输入‘/’后继续显示补全
        commands = CustomCompleter()

        while True:
            try:
                message = session.prompt(
                    '> ', completer=commands, complete_while_typing=True, key_bindings=key_bindings)

                if message.startswith('/'):
                    command = message.strip().lower()
                    handle_command(command, chatGPT, chat_settings)
                else:
                    if not message:
                        continue

                    log.info(f"> {message}")
                    with console.status("[bold cyan]ChatGPT is thinking...") as status:
                        reply = chatGPT.send(message, chat_settings.timeout)

                    if reply:
                        log.info(f"ChatGPT: {reply['content']}")
                        print_message(reply, chat_settings)

                    if message.lower() in ['再见', 'bye', 'goodbye', '结束', 'end', '退出', 'exit', 'quit']:
                        break

            except KeyboardInterrupt:
                continue
            except EOFError:
                console.print("Exiting...")
                break

    finally:
        log.info(f"Total tokens used: {chatGPT.total_tokens}")
    console.print(
        f"[bright_magenta]Total tokens used: [bold]{chatGPT.total_tokens}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Chat with GPT-3.5')
    parser.add_argument('--load', metavar='FILE', type=str, help='Load chat history from file')
    parser.add_argument('--key', type=str, help='choose the API key to load')
    parser.add_argument('-m', '--multi', action='store_true',
                        help='Enable multi-line mode')
    parser.add_argument('-r', '--raw', action='store_true',
                        help='Enable raw mode')
    args = parser.parse_args()

    main(args)
