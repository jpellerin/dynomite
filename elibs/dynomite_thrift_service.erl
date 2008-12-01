-module(dynomite_thrift_service).

-export([start_link/1, stop/1,
         handle_function/2,

         % Internal
         put/3,
         get/1,
         has/1,
         remove/1
]).

-include("config.hrl").
-include("dynomite_types.hrl").
-include("profile.hrl").

%%%%% EXTERNAL INTERFACE %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

start_link(#config{thrift_port = Port}) ->
    application:load(thrift),
    thrift_server:start_link(Port, dynomite_thrift, ?MODULE).

stop(Server) ->
    thrift_server:stop(Server),
    ok.

%%%%% THRIFT INTERFACE %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

handle_function(Function, Args) when is_atom(Function), is_tuple(Args) ->
    case apply(?MODULE, Function, tuple_to_list(Args)) of
        ok -> ok;
        Reply -> {reply, Reply}
    end.



put(Key, ContextData, Data) when
  is_binary(Key),
  (ContextData =:= undefined orelse is_binary(ContextData)),
  is_binary(Data) ->
    ?prof(Key, {start, put}),
    Context = if
                  ContextData =:= undefined -> [];
                  erlang:byte_size(ContextData) > 0 -> binary_to_term(ContextData);
                  true -> []
              end,
    Response = case mediator:put(binary_to_list(Key), Context, Data) of
                   {ok, N} -> N;
                   {failure, Reason} -> throw(#failureException{message = iolist_to_binary(Reason)})
               end,
    ?prof(Key, {'end', put}),
    Response.
                   

get(Key) when is_binary(Key) ->
    ?prof(Key, {start, get}),
    Response = case mediator:get(binary_to_list(Key)) of
                   {ok, not_found} -> #getResult{results = []};
                   {ok, {Context, Values}} ->
                       #getResult{context = term_to_binary(Context),
                                  results = Values};
                   {failure, Error} ->
                       throw(#failureException{message = iolist_to_binary(Error)})
               end,
    ?prof(Key, {'end', get}),
    Response.
    


has(Key) when is_binary(Key) ->
    case mediator:has_key(binary_to_list(Key)) of
        {ok, {Bool, N}} when is_boolean(Bool) ->
             N
    end.

remove(Key) when is_binary(Key) ->
    {ok, N} = mediator:delete(binary_to_list(Key)),
    N.

