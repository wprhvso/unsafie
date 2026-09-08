{
  description = "unsafie: the bot, the pool and the CLI";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
      ];
      forEach = nixpkgs.lib.genAttrs systems;
    in
    {
      devShells = forEach (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          default = pkgs.mkShell {
            packages = with pkgs; [
              uv
              ruff
              nodejs_22
              postgresql_17
              redis
              git
              gh
              jq
              ripgrep
              chromium
              xorg.xorgserver
              xdotool
            ];

            shellHook = ''
              export UV_PROJECT_ENVIRONMENT="$PWD/python/.venv"
              echo "unsafie dev shell — uv sync --all-packages, then uv run unsafie help"
            '';
          };
        }
      );
    };
}
