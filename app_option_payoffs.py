import dash
import dash_core_components as dcc
import dash_html_components as html
import dash_table
import pandas as pd
import plotly.graph_objs as go
import numpy as np
import pyodbc


# connect to database and store all portfolio holdings data in a dataframe
server = 'imlvs03\sql2005'
database = 'DW_Development'
driver = '{ODBC Driver 13 for SQL Server}'
conn = pyodbc.connect(driver=driver, server=server, database=database, trusted_connection='yes')
sql = '''SELECT * FROM [Rishi].[Rishi].[FUNDS: Portfolio Holdings]
    where [As At Date] in (Select max([As At Date]) from [Rishi].[Rishi].[FUNDS: Portfolio Holdings])'''
df = pd.read_sql(sql, conn)

# get list of unique portfolio codes
portfolios = df['Portfolio Code'].unique().tolist()
portfolios.sort()
prt_options = [dict(label=str(prt), value=str(prt)) for prt in portfolios]
fields = ['Security', 'Security Type', 'Unit Holding', 'Lot Size', 'Expiry Date', 'Market Price', 'Excercise Price',
          'Average Cost', 'Total Cost']

external_stylesheets = ['https://codepen.io/chriddyp/pen/bWLwgP.css']
app = dash.Dash(__name__, external_stylesheets=external_stylesheets)

app.layout = html.Div([

    # Hidden div inside the app for use with arbitrary callback
    html.Div(id='hidden', style={'display': 'none'}),

    # store component to store the filtered dataframe
    dcc.Store(id='filtered_df', modified_timestamp=0),

    # App Heading
    html.Div([
        html.H1(
            children='Option Payoffs',
            style={
                'textAlign': 'center'
            }
        )
    ]),

    # Portfolio drop down box
    html.Div([
        html.Label('Select Portfolio:'),
        dcc.Dropdown(
            id='prt-dropdown',
            options=prt_options

        )

    ], style={'display': 'table-cell', 'width': '25%'}),

    # Issuer drop down box
    html.Div([
        html.Label('Select Issuer'),
        dcc.Dropdown(
            id='issuer-dropdown'
        )
    ], style={'display': 'table-cell', 'width': '25%'}),

    # dash table
    html.Div([
        dash_table.DataTable(
            id='sec_table',
            columns=[{'name': i, 'id': i} if i != 'Security Type'
                else {'name': i, 'id': i, 'presentation': 'dropdown'} for i in fields],
            column_static_dropdown=[{
                'id': 'Security Type',
                'dropdown': [{'label': i, 'value': i} for i in ['OS', 'CO', 'PO']]
            }],
            editable=True,
            row_deletable=True,
            data_timestamp=0
        )
    ], style={'width': '50%'}),

    # add security button
    html.Button('Add Security', id='add_rows_button', n_clicks_timestamp=0),

    # option payoff chart
    html.Div([
        dcc.Graph(
            id='payoff_graph'
        )
    ], style={'width': '50%'})

])

# callback function to filter dataframe on user entered portfolio code
# returns list of dictionary options for issuer drop down menu
@app.callback(
    dash.dependencies.Output('issuer-dropdown', 'options'),
    [dash.dependencies.Input('prt-dropdown', 'value')]
)
def update_issuer_dropdown(prt):
    df_filter = df[(df['Portfolio Code'] == prt) & (df['Security Type'] != 'ZL')]
    issuers = df_filter['Issuer'].unique().tolist()
    issuers.sort()
    return [dict(label=str(issuer), value=str(issuer)) for issuer in issuers]

# callback function to return a dataframe that contains issuer data for the selected portfolio and issuer code
@app.callback(
    dash.dependencies.Output('filtered_df', 'data'),
    [dash.dependencies.Input('prt-dropdown', 'value'),
     dash.dependencies.Input('issuer-dropdown', 'value')]
)
def clean_data(prt, issuer):
    print('storing issuer data in dataframe')
    if prt is not None and issuer is not None:
        sec_types = ['OS', 'CO', 'PO']
        df_filter = df[(df['Portfolio Code'] == prt) & (df['Security Type'].isin(sec_types)) &
            (df['Issuer'] == issuer)].copy()
        df_filter = df_filter[((df_filter['Security Type'] == 'OS') & (df_filter['Security'].str.len() == 3)) |
            (df_filter['Security Type'].isin(['CO', 'PO']))].copy()
        df_filter['Average Cost'] = df_filter['Total Cost'] / (df_filter['Unit Holding'] * df_filter['Lot Size'])
        df_filter = df_filter.loc[:, fields].copy()
        return df_filter.to_dict('rows')

    else:
        return [{}]

# callback function to display row data on table
@app.callback(
    dash.dependencies.Output('sec_table', 'data'),
    [dash.dependencies.Input('filtered_df', 'modified_timestamp'),
     dash.dependencies.Input('add_rows_button', 'n_clicks_timestamp'),
     dash.dependencies.Input('sec_table', 'data_timestamp')],
    [dash.dependencies.State('filtered_df', 'data'),
     dash.dependencies.State('sec_table', 'data'),
     dash.dependencies.State('sec_table', 'columns')]
)
def display_rows(drop_down_time, add_rows_time, edit_table_time, df, rows, columns):

    # if current table is nothing
    if rows is None:
        return df

    # use timestamp to figure out which action was taken last
    if drop_down_time > add_rows_time and drop_down_time > edit_table_time:
        return df

    elif add_rows_time > drop_down_time and add_rows_time > edit_table_time:
        rows.append({c['id']: '' for c in columns})
        return rows

    elif edit_table_time > drop_down_time and edit_table_time > add_rows_time:
        for row in rows:
            try:
                row['Total Cost'] = float(row['Average Cost']) * float(row['Unit Holding']) * float(row['Lot Size'])

            except:
                row['Total Cost'] = ''

        return rows

# arbitrary callback so editable table will update when user makes a selection from the drop down menu
@app.callback(
    dash.dependencies.Output('hidden', 'children'),
    [dash.dependencies.Input('sec_table', 'data_timestamp')]
)
def dummy(d):
    raise dash.exceptions.PreventUpdate

# callback function to update payoff chart
@app.callback(
    dash.dependencies.Output('payoff_graph', 'figure'),
    [dash.dependencies.Input('filtered_df', 'data')]
)
def update_chart(data):
    print('chart update')
    if data == [{}]:
        raise dash.exceptions.PreventUpdate

    df_filter = pd.DataFrame(data=data)
    issuer = df_filter[df_filter['Security Type'] == 'OS']['Security'].values[0]
    min_price = 0
    max_price = max(df_filter['Market Price'].max(), df_filter['Excercise Price'].max()) * 2
    prices = np.arange(min_price, max_price, 0.01)
    df_payoff = pd.DataFrame(index=prices)

    # calculate payoffs and store in a dataframe
    sec_count = 0
    for idx, row in df_filter.iterrows():
        if row['Security Type'] == 'OS':
            df_payoff[sec_count] = row['Unit Holding'] * df_payoff.index - row['Total Cost']

        elif row['Security Type'] == 'CO':
            payoff = df_payoff.index - row['Excercise Price']
            df_payoff.loc[payoff >= 0, sec_count] = row['Unit Holding'] * row['Lot Size'] * payoff[payoff >= 0] - \
                row['Total Cost']
            df_payoff.loc[payoff < 0, sec_count] = 0 - row['Total Cost']

        elif row['Security Type'] == 'PO':
            payoff = row['Excercise Price'] - df_payoff.index
            df_payoff.loc[payoff >= 0, sec_count] = row['Unit Holding'] * row['Lot Size'] * payoff[payoff >= 0] - \
                row['Total Cost']
            df_payoff.loc[payoff < 0, sec_count] = 0 - row['Total Cost']

        sec_count += 1

    df_payoff.loc[:, 'Total'] = df_payoff.sum(axis=1)

    # option payoff chart
    scatter = [go.Scatter(
        x=df_payoff.index,
        y=df_payoff['Total'],
        mode='lines',
        name=issuer,
        showlegend=False
    )]

    strikes = df_filter.loc[df_filter['Excercise Price'] > 0, 'Excercise Price']
    for strike in strikes:
        scatter.append(go.Scatter(
            x=df_payoff.loc[df_payoff.index == strike, :].index,
            y=df_payoff.loc[df_payoff.index == strike, 'Total'],
            mode='markers',
            showlegend=False
        ))

    layout = dict(title='Payoff',
                  xaxis=dict(title='Stock Price'),
                  yaxis=dict(title='P&L ($)')
                  )

    figure = dict(data=scatter, layout=layout)

    return figure


if __name__ == '__main__':
    app.run_server(debug=True)