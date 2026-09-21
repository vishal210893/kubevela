GWFS_NPM_BIN="/home/node/.npm-global/bin"

case ":$PATH:" in
    *":$GWFS_NPM_BIN:"*) ;;
    *) export PATH="$GWFS_NPM_BIN:$PATH" ;;
esac
