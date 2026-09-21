GWFS_BUN_BIN="/home/node/.bun/bin"

case ":$PATH:" in
    *":$GWFS_BUN_BIN:"*) ;;
    *) export PATH="$GWFS_BUN_BIN:$PATH" ;;
esac
