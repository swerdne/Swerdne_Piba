# mcp-video-editor

Servidor **MCP (Model Context Protocol)** de edição de vídeo baseado em **FFmpeg**.
Com ele, o Claude (Code ou Desktop) corta, junta, legenda, escreve texto, põe marca
d'água, troca trilha, muda velocidade, redimensiona, converte e extrai frames de vídeos
que estão numa pasta da sua máquina.

- Python 3.11+, SDK oficial `mcp` (FastMCP), transporte **stdio**
- FFmpeg/FFprobe via `asyncio.create_subprocess_exec` (nunca `shell=True`), com timeout
- Todos os caminhos ficam presos ao diretório de trabalho (`VIDEO_WORKDIR`)
- Nunca sobrescreve arquivo existente sem `overwrite=true`; a saída é escrita num arquivo
  temporário e só renomeada no fim (falha ou timeout não deixam arquivo pela metade)
- Logs só no stderr (stdout é do protocolo)

## Estrutura

```
mcp-video-editor/
├── server.py            # FastMCP + stdio, checagem do ffmpeg na inicialização
├── ffmpeg_utils.py      # sandbox de caminhos, validação, execução async do ffmpeg/ffprobe
├── tools/
│   ├── __init__.py      # register_all(mcp)
│   ├── _common.py       # codecs padrão por contêiner, crf/preset
│   ├── info.py          # get_video_info, list_media_files
│   ├── editing.py       # trim_video, concat_videos, change_speed, resize_video
│   ├── audio.py         # extract_audio, add_audio, remove_audio
│   ├── effects.py       # add_text_overlay, add_subtitles, add_watermark
│   └── export.py        # convert_format, extract_frames
├── tests/               # pytest; vídeos de teste gerados pelo próprio ffmpeg
├── pyproject.toml       # dependências (uv)
├── uv.lock
└── requirements.txt     # alternativa ao uv
```

## Instalação

1. **FFmpeg** (precisa ter `ffmpeg` e `ffprobe` no PATH; builds com `libfreetype` e
   `libass` para texto e legendas — as dos gerenciadores abaixo já têm):

   ```bash
   sudo apt install ffmpeg        # Debian/Ubuntu
   brew install ffmpeg            # macOS
   winget install Gyan.FFmpeg     # Windows
   ```

2. **Dependências Python** — com [uv](https://docs.astral.sh/uv/) (recomendado):

   ```bash
   cd mcp-video-editor
   uv sync                # cria .venv com mcp + pytest
   ```

   ou com pip:

   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. Testar se sobe (Ctrl+C para sair; os logs aparecem no stderr):

   ```bash
   VIDEO_WORKDIR=~/Videos uv run server.py
   ```

> O SDK é fixado em `mcp>=1.12,<2`: na série 2.x o `FastMCP` foi renomeado para `MCPServer`.

## Configuração (variáveis de ambiente)

| Variável | Padrão | O que faz |
|---|---|---|
| `VIDEO_WORKDIR` | `./workspace` | Pasta raiz. Toda entrada e saída precisa estar dentro dela (`..`, caminhos absolutos fora e symlinks para fora são recusados). |
| `VIDEO_FFMPEG_TIMEOUT` | `900` | Tempo máximo (s) de cada comando do ffmpeg; ao estourar, o processo é morto. |
| `VIDEO_MAX_JOBS` | `2` | Quantos ffmpeg rodam ao mesmo tempo (os demais esperam na fila). |
| `FFMPEG_BIN` / `FFPROBE_BIN` | PATH | Caminho dos executáveis, se não estiverem no PATH. |
| `VIDEO_LOG_LEVEL` | `INFO` | Nível de log (stderr). |

## Registrar no Claude Code

```bash
cd mcp-video-editor
claude mcp add video-editor -- uv run server.py
```

Com pasta de trabalho e caminho absoluto (funciona de qualquer diretório):

```bash
claude mcp add video-editor \
  -e VIDEO_WORKDIR="$HOME/Videos" \
  -- uv run --directory /caminho/para/mcp-video-editor server.py
```

Confira com `claude mcp list` (ou `/mcp` dentro do Claude Code).

## Claude Desktop (`claude_desktop_config.json`)

macOS: `~/Library/Application Support/Claude/claude_desktop_config.json` ·
Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "video-editor": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/caminho/absoluto/para/mcp-video-editor",
        "server.py"
      ],
      "env": {
        "VIDEO_WORKDIR": "/Users/voce/Videos/edicao",
        "VIDEO_FFMPEG_TIMEOUT": "1800"
      }
    }
  }
}
```

No Windows use barras duplas (`"C:\\Users\\voce\\mcp-video-editor"`). Se o Claude
Desktop não achar o `uv`, coloque o caminho completo em `command`
(`which uv` / `where uv`). Reinicie o Claude Desktop depois de editar.

## Tools

Todos os caminhos são relativos a `VIDEO_WORKDIR`. Tempos aceitam segundos (`12.5`) ou
`HH:MM:SS(.ms)`. Toda tool que gera arquivo devolve `{ok, output, duration_seconds,
resolution, fps, has_audio, size_human, ...}`.

| Tool | Para quê | Parâmetros principais |
|---|---|---|
| `get_video_info` | duração, resolução, fps, codecs, tamanho, se tem áudio | `path` |
| `list_media_files` | lista vídeos/áudios/imagens/legendas do workdir | `subdir` |
| `trim_video` | corta um trecho | `input, start, end \| duration, output, fast` |
| `concat_videos` | junta vídeos em sequência (cópia direta se compatíveis; senão recodifica no formato do 1º) | `inputs[], output, reencode` |
| `extract_audio` | salva o áudio em mp3/aac/m4a/wav/flac/ogg/opus | `input, output, format` |
| `add_audio` | troca (`mix=false`) ou mistura (`mix=true`) a trilha, com volumes, atraso e loop | `video, audio, output, mix, audio_volume, original_volume, audio_start, loop_audio` |
| `add_text_overlay` | escreve texto, opcionalmente só entre `start` e `end` | `input, text, position, font_size, color, start, end, box, font_file, output` |
| `add_subtitles` | queima legenda .srt/.ass/.vtt | `input, srt_path, output, font_size, font_color` |
| `change_speed` | acelera/desacelera imagem e áudio juntos (0.25×–4×) | `input, factor, output` |
| `resize_video` | redimensiona; `fit`/`pad` (barras), `crop` (preenche e corta) ou `stretch` | `input, width, height, mode, output` |
| `add_watermark` | sobrepõe logo com posição, opacidade e tamanho relativo | `input, image, position, opacity, scale, output` |
| `convert_format` | converte contêiner/codec (h264, h265, vp9, av1, copy) e comprime por `crf` | `input, output, codec, crf, preset` |
| `extract_frames` | sequência de frames (`fps`) ou uma thumbnail (`timestamp`) | `input, output_dir, fps, timestamp, format, width, max_frames` |
| `remove_audio` | deixa o vídeo mudo, sem recodificar | `input, output` |

Todas aceitam `overwrite` (padrão `false`). As que demoram reportam **progresso** ao
cliente MCP (`notifications/progress`) a partir do `-progress` do ffmpeg.

`position` aceita: `top-left`, `top`, `top-right`, `left`, `center`, `right`,
`bottom-left`, `bottom`, `bottom-right`.

## Exemplos de uso (pedindo ao Claude)

> Corte `brutos/culto.mp4` de 00:12:30 até 00:15:00 e salve em `cortes/louvor.mp4`.

→ `trim_video(input="brutos/culto.mp4", start="00:12:30", end="00:15:00", output="cortes/louvor.mp4")`

> Faça uma versão vertical para Reels, com o título "Domingo 19h" no topo e o logo no canto.

→ `resize_video(..., width=1080, height=1920, mode="crop")` →
`add_text_overlay(..., text="Domingo 19h", position="top", font_size=72, box=true)` →
`add_watermark(..., image="logo.png", position="bottom-right", opacity=0.8)`

> Põe a `musica.mp3` baixinha de fundo, mantendo a voz.

→ `add_audio(video="v.mp4", audio="musica.mp3", output="v_musica.mp4", mix=true, audio_volume=0.2)`

> Comprime para mandar no WhatsApp.

→ `convert_format(input="v.mp4", output="v_whats.mp4", codec="h264", crf=28, preset="medium")`

> Gera uma capa do segundo 5.

→ `extract_frames(input="v.mp4", output_dir="capas", timestamp="5", format="jpg")`

## Erros

Erros de validação e do ffmpeg voltam como resultado de erro da tool (`isError: true`)
com mensagem legível — ex.:

```
O arquivo 'saida.mp4' já existe. Use overwrite=true para substituí-lo ou escolha outro nome.
Caminho de entrada fora do diretório de trabalho: '../segredo.mp4'. Use caminhos relativos a /home/voce/Videos.
O ffmpeg falhou (código 1):
[mov,mp4,m4a,3gp,3g2,mj2 @ 0x...] moov atom not found
brutos/x.mp4: Invalid data found when processing input
```

O stderr do ffmpeg é resumido (últimas linhas relevantes, sem banner nem progresso).

## Segurança

- Sandbox: caminhos resolvidos com `Path.resolve()` (segue symlinks) e conferidos com
  `is_relative_to(VIDEO_WORKDIR)`; NUL e extensões fora da lista são recusados.
- Sem shell: argumentos passados como lista ao `create_subprocess_exec`.
- Textos e caminhos que entram em filtros do ffmpeg são escapados nos dois níveis
  (opção e filtergraph); o texto do `add_text_overlay` vai num arquivo (`textfile=`,
  `expansion=none`), então `%{...}`, aspas e `:` do usuário não viram código de filtro.
- Limites: timeout por comando, fila de jobs, `max_frames`, faixas validadas para
  velocidade, tamanho, crf, volume etc.

## Testes

```bash
uv run pytest -q          # ou: .venv/bin/python -m pytest -q
```

Os testes geram vídeos de 2–3 s com `testsrc`/`sine` do próprio ffmpeg, rodam as 13
tools de verdade (conferindo duração/resolução/áudio do resultado com ffprobe), testam
sandbox, overwrite, timeout e escape de filtros, e sobem o servidor com um cliente MCP
em memória para checar a lista de tools e os erros pelo protocolo. Sem ffmpeg ou sem o
SDK `mcp<2`, os testes são ignorados (não quebram a suíte de quem roda da raiz do repo).
