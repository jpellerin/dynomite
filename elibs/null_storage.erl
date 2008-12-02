-module (null_storage).
-export ([open/2, close/1, get/2, put/4, has_key/2, fold/3, delete/2, info/1]).

% we ignore the name, since it can't really help us.
open(_, _) -> {ok, dict:new()}.

% noop
close(_Table) -> ok.

info(Table) -> dict:fetch_keys(Table).

fold(Fun, Table, AccIn) when is_function(Fun) ->
  dict:fold(fun(Key, {Context, [Value]}, Acc) ->
      Fun({Key, Context, Value}, Acc)
    end, AccIn, Table).

put(Key, Context, Value, Table) ->
	{ok, Table}.
	
get(Key, Table) ->
    {ok, not_found}.
	
has_key(Key, Table) ->
	{ok, true}.
	
delete(Key, Table) ->
	{ok, Table}.
